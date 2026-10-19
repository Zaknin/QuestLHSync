"""P3-A producer archive synthetic tests; never connects to Android."""
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pico.tools import p3a_collect_producers as m
from pico.tools.p3a_quickcamera_inventory import CAMERA_SHA, SAFETY


def elf64():
    b = bytearray(64)
    b[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', b, 18, 183)
    return bytes(b)


def inventory():
    cam = '/system/lib64/libpvrtrackingcamera.so'
    sys = '/system/lib64/pico.camera.quickcamera.common@1.0.so'
    ven = '/vendor/lib64/pico.camera.quickcamera.common@1.0.so'
    core = '/vendor/lib64/quickcamera.core.so'
    digest = hashlib.sha256(elf64()).hexdigest()
    name = sys.rsplit('/', 1)[1]
    return {'status': 'INVENTORY_READY', 'p2_sha_match': True,
            'pvr_candidate_hashes': {cam: CAMERA_SHA}, 'p2_exact_camera_paths': [cam],
            'safety': SAFETY, 'device': {'ro.build.fingerprint': 'fingerprint-x'},
            'p2_pinned_dt_needed': [name],
            'same_abi_dependency_paths': {name: [sys, ven]},
            'additional_producer_candidates': [core],
            'producer_hashes': {sys: digest, ven: digest, core: digest}}


class ExtractionTests(unittest.TestCase):
    def test_trusted_inventory_sha_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / 'p3a-inventory-test.json'
            raw = json.dumps(inventory()).encode()
            f.write_bytes(raw)
            f.with_suffix('.sha256').write_text(hashlib.sha256(raw).hexdigest()+'  '+f.name+'\n')
            o, digest = m.trusted_inventory(f)
            self.assertTrue(o['p2_sha_match'])
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            f.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                m.trusted_inventory(f)

    def test_path_traversal_rejected(self):
        for p in ('/vendor/lib64/../../data/key.so', '/tmp/bad.so',
                  '/system/lib64/libx.so;id', '/vendor/lib/libx.so'):
            self.assertFalse(m.valid_path(p))
        obj = inventory()
        obj['producer_hashes']['/tmp/bad.so'] = '1'*64
        with self.assertRaises(ValueError):
            m.select_producers(obj)

    def test_preserve_system_and_vendor_variants(self):
        paths = m.select_producers(inventory())
        self.assertEqual(len(paths), 3)
        self.assertTrue(any(p.startswith('/system/lib64/') for p in paths))
        self.assertTrue(any(p.startswith('/vendor/lib64/') for p in paths))

    def test_reject_wrong_elf_architecture(self):
        m.validate_arm64_elf(elf64())
        for raw in (b'abcd', elf64()[:4]+b'garbage'*10, elf64()[:4]+b'\x01'+elf64()[5:]):
            with self.assertRaises(ValueError):
                m.validate_arm64_elf(raw)

    def test_full_verified_copy_and_archive(self):
        calls = []
        def rh(serial, path):
            calls.append(('hash',path))
            return hashlib.sha256(elf64()).hexdigest()
        def pull(serial, op, path, target, **kw):
            self.assertEqual(op, 'pull')
            calls.append(('pull',path))
            Path(target).write_bytes(elf64())
        def props(serial, *args, **kw):
            return 'device' if args == ('get-state',) else 'fingerprint-x'
        with tempfile.TemporaryDirectory() as td:
            r = m.collect(inventory(), 'a'*64, 'mock', Path(td),
                          read_device_hash=rh, pull=pull, read_getprop=props)
            self.assertEqual(r['status'], 'PACKAGE_READY')
            self.assertEqual(r['verified_count'], 3)
            self.assertEqual(sum(c[0]=='pull' for c in calls), 3)
            with zipfile.ZipFile(io.BytesIO(m.build_zip(Path(td),r))) as z:
                self.assertEqual(len(z.namelist()), 4)
                self.assertFalse(json.loads(z.read('manifest.json'))['timestamp_producer_verified'])

    def test_hash_mismatch_keeps_partial_package(self):
        rejected = next(iter(m.select_producers(inventory())))
        def rh(s,p):
            return '0'*64 if p==rejected else hashlib.sha256(elf64()).hexdigest()
        def pull(s, op,p,target, **kw):
            Path(target).write_bytes(elf64())
        def props(s,*args, **kw):
            return 'device' if args == ('get-state',) else 'fingerprint-x'
        with tempfile.TemporaryDirectory() as td:
            r=m.collect(inventory(),'b'*64,'mock',Path(td),
                        read_device_hash=rh,pull=pull,read_getprop=props)
            self.assertEqual((r['status'],r['verified_count'],len(r['errors'])),('PARTIAL',2,1))
            with zipfile.ZipFile(io.BytesIO(m.build_zip(Path(td),r))) as z:
                self.assertEqual(len(z.namelist()),3)

    def test_firmware_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            r=m.collect(inventory(),'a'*64,'mock',Path(td),
                        read_getprop=lambda *args,**kw: 'device' if args[1:]==('get-state',) else 'wrong')
            self.assertEqual(r['status'],'BLOCKED')

    def test_atomic_sidecar_last_and_corrupt_readback(self):
        record={'status':'BLOCKED','files':[],'errors':[{'stage':'mock'}],'safety':SAFETY}
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            r=m.canonical_commit(root,'test',record,b'blocked diagnostic')
            self.assertEqual(hashlib.sha256(Path(r['zip']).read_bytes()).hexdigest(),r['package_digest'])
            self.assertTrue(Path(r['sha256']).is_file())
            self.assertFalse(list(root.glob('*.part')))
            published = {suffix: (root / f'test.{suffix}').read_bytes()
                         for suffix in ('zip', 'manifest.json', 'sha256')}
            with self.assertRaisesRegex(FileExistsError, 'already has'):
                m.canonical_commit(root,'test',record,b'replacement')
            self.assertEqual((root/'test.zip').read_bytes(), published['zip'])
            self.assertEqual((root/'test.manifest.json').read_bytes(), published['manifest.json'])
            self.assertEqual((root/'test.sha256').read_bytes(), published['sha256'])
            with self.assertRaisesRegex(ValueError, 'package name'):
                m.canonical_commit(root,'../escape',record,b'data')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaisesRegex(IOError,'readback'):
                m.canonical_commit(root,'corrupt',record,b'data',readback=lambda p:b'corrupt')
            self.assertFalse((root/'corrupt.sha256').exists())
            self.assertFalse(list(root.glob('*.part')))

    def test_canonical_commit_missing_errors_returns_receipt_and_commits_sidecar_last(self):
        record={'status':'PARTIAL','files':[],'safety':SAFETY}
        replacements=[]
        real_replace=m.os.replace

        def record_replace(source, destination):
            replacements.append(Path(destination).name)
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(m.os, 'replace', side_effect=record_replace):
                receipt=m.canonical_commit(root,'diagnostic',record,b'partial diagnostic')
            self.assertEqual(receipt['status'],'PARTIAL')
            self.assertEqual(receipt['errors'],[])
            self.assertEqual(replacements,['diagnostic.zip','diagnostic.manifest.json','diagnostic.sha256'])
            self.assertEqual(hashlib.sha256(Path(receipt['zip']).read_bytes()).hexdigest(),receipt['package_digest'])
            self.assertFalse(list(root.glob('*.part')))


if __name__ == '__main__':
    unittest.main()
