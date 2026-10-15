import android.os.IBinder;
import android.os.Parcel;
import android.os.SharedMemory;
import android.os.SystemClock;
import android.system.OsConstants;

import java.io.BufferedOutputStream;
import java.io.DataOutputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Pico OS 5.11.2 / Pico 4 Pro read-only K0 camera bridge. Stdout is BINARY. */
public final class PicoFrameReader {
    private static final int[] CAMERAS = {0, 3, 4, 5};
    private static final int[] SENSORS = {0, 1, 2, 3};
    private static final int TRANSACTION = 19; // pvr.ITrackingService.GetCameraShareMemory
    private static final int HEADER = 20, STRIDE = 308026, SLOTS = 5;
    private static final int WIDTH = 640, HEIGHT = 480, PIXELS = WIDTH * HEIGHT;
    private static final int RING_SIZE = HEADER + STRIDE * SLOTS, PIXEL_OFFSET = 186;
    private static final long MAX_NS_GAP = 2_000_000_000L;
    // Opt-in text on stderr, NEVER in stdout's PFR1 binary stream.
    // The default production stream is byte-for-byte unchanged.
    private static final boolean FRAME_CLOCK_DIAG =
        "1".equals(System.getenv("PICO_FRAME_CLOCK_DIAG"));

    private static final class Camera implements AutoCloseable {
        final int id;
        final SharedMemory shm;
        final ByteBuffer view;
        final byte[] pixels = new byte[PIXELS];
        long lastSequence;
        long diagnosticFrames;

        Camera(IBinder service, String descriptor, int id, int sensor) throws Exception {
            this.id = id;
            Parcel req = Parcel.obtain(), reply = Parcel.obtain();
            SharedMemory memory = null;
            ByteBuffer mapped = null;
            try {
                req.writeInterfaceToken(descriptor);
                req.writeInt(id);
                req.writeInt(0); // ONLY K0, short exposure; never request IDs >= 7.
                if (!service.transact(TRANSACTION, req, reply, 0))
                    throw new IllegalStateException("C" + id + ": Binder transact failed");
                try {
                    reply.readException();
                } catch (RuntimeException e) {
                    throw new IllegalStateException("C" + id +
                        " K0 GetCameraShareMemory transaction 19 rejected: " + e, e);
                }
                int status = reply.readInt();
                if (status != 0 || reply.readInt() != 1)
                    throw new IllegalStateException("C" + id + ": no K0 ring, status " + status);
                memory = SharedMemory.CREATOR.createFromParcel(reply);
                int declared = reply.readInt();
                if (declared != RING_SIZE || memory.getSize() != RING_SIZE)
                    throw new IllegalStateException("C" + id + ": unexpected ring size " + declared);
                mapped = memory.map(OsConstants.PROT_READ, 0, RING_SIZE);
                mapped.order(ByteOrder.LITTLE_ENDIAN);
                if (mapped.getInt(0) != 1 || mapped.getInt(4) != STRIDE ||
                    mapped.getInt(8) != SLOTS || mapped.getInt(16) != HEADER ||
                    (mapped.get(HEADER + 97) & 255) != sensor)
                    throw new IllegalStateException("C" + id + ": ring metadata/sensor mismatch");
            } catch (Exception e) {
                if (mapped != null) SharedMemory.unmap(mapped);
                if (memory != null) memory.close();
                throw e;
            } finally {
                req.recycle();
                reply.recycle();
            }
            shm = memory;
            view = mapped;
        }

        /** Return number of accepted frames; select only completed slots, oldest first. */
        int poll(DataOutputStream out) throws Exception {
            int idx = view.getInt(12);
            if (idx < 0 || idx >= SLOTS) return 0;
            long[] seq = new long[SLOTS], ts = new long[SLOTS];
            long newest = 0;
            for (int i = 0; i < SLOTS; i++) {
                int base = HEADER + i * STRIDE;
                seq[i] = view.getLong(base + 146);
                ts[i] = view.getLong(base + 122); // vendor candidate; not yet clock-validated
                if (seq[i] > newest) newest = seq[i];
            }
            if (newest <= 0) return 0;
            if (lastSequence == 0) { lastSequence = newest; return 0; }
            int copied = 0;
            for (int attempt = 0; attempt < SLOTS; attempt++) {
                long next = Long.MAX_VALUE;
                int chosen = -1;
                for (int i = 0; i < SLOTS; i++)
                    if (seq[i] > lastSequence && seq[i] < newest && seq[i] < next &&
                        (seq[i] & 1L) == 1L && ts[i] > 0) {
                        next = seq[i];
                        chosen = i;
                    }
                if (chosen < 0) break;
                int base = HEADER + chosen * STRIDE;
                long writeLockBootNs = FRAME_CLOCK_DIAG ? view.getLong(base + 84) : 0L;
                int exposure = view.getInt(base + 110);
                if (exposure != 4)
                    throw new IllegalStateException("C" + id + ": K0 exposure changed to " + exposure);
                ByteBuffer frame = view.duplicate();
                frame.position(base + PIXEL_OFFSET);
                frame.get(pixels, 0, PIXELS);
                long readNs = System.nanoTime();
                long readBootNs = FRAME_CLOCK_DIAG ? SystemClock.elapsedRealtimeNanos() : 0L;
                if (view.getInt(12) != idx || view.getLong(base + 146) != next ||
                    (FRAME_CLOCK_DIAG && view.getLong(base + 84) != writeLockBootNs) ||
                    view.getLong(base + 122) != ts[chosen] || view.getInt(base + 110) != exposure)
                    break; // discard a potentially torn read; try again next poll
                // Big-endian records; never print human-readable messages to stdout.
                out.writeInt(0x50465231); // "PFR1"
                out.writeInt(id);
                out.writeLong(next);
                out.writeLong(ts[chosen]);
                out.writeLong(readNs); // Android System.nanoTime: CLOCK_MONOTONIC
                out.writeInt(exposure);
                out.writeInt(PIXELS);
                out.write(pixels);
                out.flush(); // native reader must see each frame immediately
                lastSequence = next;
                seq[chosen] = -1;
                copied++;
                if (FRAME_CLOCK_DIAG && ++diagnosticFrames % 125 == 0) {
                    // One read per 5 seconds per camera. Same ring slot and
                    // sequence as the just-emitted PFR1 frame.
                    System.err.println("PicoFrameClock cam=" + id +
                        " seq=" + next +
                        " producer_write_boot_ns=" + writeLockBootNs +
                        " java_copy_mono_ns=" + readNs +
                        " java_copy_boot_ns=" + readBootNs +
                        " producer_to_copy_ms=" +
                        ((readBootNs - writeLockBootNs) / 1e6));
                }
            }
            return copied;
        }

        @Override public void close() {
            SharedMemory.unmap(view);
            shm.close();
        }
    }

    private static IBinder getService() throws Exception {
        Class<?> sm = Class.forName("android.os.ServiceManager");
        Method m = sm.getDeclaredMethod("getService", String.class);
        return (IBinder) m.invoke(null, "pvrtracking");
    }

    /** Single-shot Binder health check, no frame capture and no binary stdout. */
    private static void probe() throws Exception {
        IBinder svc = getService();
        if (svc == null || !"pvr.ITrackingService".equals(svc.getInterfaceDescriptor()))
            throw new IllegalStateException("pvr.ITrackingService unavailable");
        boolean failed = false;
        for (int i = 0; i < CAMERAS.length; i++) {
            int id = CAMERAS[i];
            try (Camera camera = new Camera(svc, "pvr.ITrackingService", id, SENSORS[i])) {
                System.err.println("Pico K0 C" + id + ": OK (ring mapped and metadata verified)");
            } catch (Throwable e) {
                failed = true;
                System.err.println("Pico K0 C" + id + ": FAILED: " + e);
            }
        }
        if (failed) System.exit(3);
    }

    /**
     * Read-only single-camera diagnostic for the two Android clock domains.
     * BOOTTIME includes suspend, MONOTONIC does not. Vendor slot+122 is still
     * only a candidate timestamp; this probe does not reinterpret F records.
     * Emit diagnostics to stderr, never mixing them with the binary stream.
     */
    private static void probeClock() throws Exception {
        IBinder svc = getService();
        if (svc == null || !"pvr.ITrackingService".equals(svc.getInterfaceDescriptor()))
            throw new IllegalStateException("pvr.ITrackingService unavailable");
        try (Camera cam = new Camera(svc, "pvr.ITrackingService", CAMERAS[0], SENSORS[0])) {
            for (int sample = 0; sample < 12; sample++) {
                long max = 0, chosen = 0, vendor = 0;
                int beforeIndex = cam.view.getInt(12);
                for (int slot = 0; slot < SLOTS; slot++) {
                    long seq = cam.view.getLong(HEADER + slot * STRIDE + 146);
                    if (seq > max && (seq & 1L) != 0) max = seq;
                }
                for (int slot = 0; slot < SLOTS; slot++) {
                    int base = HEADER + slot * STRIDE;
                    long seq = cam.view.getLong(base + 146);
                    long timestamp = cam.view.getLong(base + 122);
                    if (seq > chosen && seq < max && (seq & 1L) != 0 && timestamp > 0) {
                        chosen = seq;
                        vendor = timestamp;
                    }
                }
                long monoBefore = System.nanoTime();
                long boot = SystemClock.elapsedRealtimeNanos();
                long monoAfter = System.nanoTime();
                long mono = monoBefore + (monoAfter - monoBefore) / 2;
                if (beforeIndex != cam.view.getInt(12) || chosen == 0) {
                    System.err.println("Pico clock sample=" + sample + " unstable/empty slot; skipped");
                } else {
                    System.err.println("Pico clock sample=" + sample + " C" + cam.id +
                        " seq=" + chosen +
                        " vendor_ns=" + vendor +
                        " boottime_ns=" + boot +
                        " monotonic_ns=" + mono +
                        " boot_minus_mono_ns=" + (boot - mono) +
                        " boot_minus_vendor_ns=" + (boot - vendor));
                }
                Thread.sleep(250);
            }
        }
    }


    /**
     * Independent P2 clock-domain scan (never opens a new capture stream).
     *
     * Reads only stable shared-memory metadata from the 4 existing K0 rings.
     * Sampling a completed (not newest) slot intentionally adds >= one frame
     * of uncertainty. Firmware DataBuffer::lockForWrite calls
     * systemTime(SYSTEM_TIME_BOOTTIME=4) into slot+84: a producer WRITE-LOCK
     * timestamp (not the camera exposure!). slot+122/130 are separate
     * vendor metadata whose epoch and exposure semantics are unverified.
     * Unlike production, this tool prints text CSV to stdout.
     */
    private static void scanClock(int seconds) throws Exception {
        if (seconds < 5 || seconds > 60)
            throw new IllegalArgumentException("--clock-scan duration must be 5..60 seconds");
        IBinder svc = getService();
        if (svc == null || !"pvr.ITrackingService".equals(svc.getInterfaceDescriptor()))
            throw new IllegalStateException("pvr.ITrackingService unavailable");
        Camera[] cc = new Camera[CAMERAS.length];
        try {
            for (int i = 0; i < CAMERAS.length; i++)
                cc[i] = new Camera(svc, "pvr.ITrackingService", CAMERAS[i], SENSORS[i]);
            System.out.println("sample,cam,seq,newest_seq,slot,ring_index,ring_ts84_ns,vendor_ns,ring_ts130_ns,mono_ns,boot_ns,boot_minus_mono_ns");
            long start = System.nanoTime(), end = start + seconds * 1_000_000_000L;
            long[] previous = new long[CAMERAS.length];
            int[] count = new int[CAMERAS.length];
            while (System.nanoTime() < end) {
                for (int k = 0; k < cc.length; k++) {
                    Camera c = cc[k];
                    int ringIdx = c.view.getInt(12);
                    if (ringIdx < 0 || ringIdx >= SLOTS) continue;
                    long newest = 0, chosen = 0, vendor = 0, ts84 = 0, ts130 = 0;
                    int chosenSlot = -1;
                    // One scan to identify the newest slot; never read that
                    // potentially in-flight slot as a stable frame.
                    for (int j = 0; j < SLOTS; j++) {
                        long q = c.view.getLong(HEADER + j * STRIDE + 146);
                        if ((q & 1L) != 0 && q > newest) newest = q;
                    }
                    for (int j = 0; j < SLOTS; j++) {
                        int base = HEADER + j * STRIDE;
                        long q = c.view.getLong(base + 146);
                        long v = c.view.getLong(base + 122);
                        if ((q & 1L) != 0 && q < newest && q > chosen && v > 0 &&
                            c.view.getInt(base + 110) == 4) {
                            chosen = q; vendor = v; ts84 = c.view.getLong(base + 84);
                            ts130 = c.view.getLong(base + 130); chosenSlot = j;
                        }
                    }
                    if (chosenSlot < 0 || chosen <= previous[k]) continue;
                    // Bracket BOOTTIME and MONOTONIC at the same snapshot.
                    long mb = System.nanoTime();
                    long bb = SystemClock.elapsedRealtimeNanos();
                    long ba = SystemClock.elapsedRealtimeNanos();
                    long ma = System.nanoTime();
                    int base = HEADER + chosenSlot * STRIDE;
                    if (ringIdx != c.view.getInt(12) ||
                        chosen != c.view.getLong(base + 146) ||
                        vendor != c.view.getLong(base + 122) ||
                        ts84 != c.view.getLong(base + 84) ||
                        ts130 != c.view.getLong(base + 130) ||
                        c.view.getInt(base + 110) != 4)
                        continue;
                    long mono = mb + (ma - mb) / 2;
                    long boot = bb + (ba - bb) / 2;
                    // No floating-point conversion of the 64-bit nanoseconds.
                    System.out.println(count[k]++ + "," + c.id + "," + chosen + "," + newest +
                        "," + chosenSlot + "," + ringIdx + "," + ts84 + "," +
                        vendor + "," + ts130 + "," + mono + "," + boot + "," + (boot - mono));
                    previous[k] = chosen;
                }
                Thread.sleep(10);
            }
            for (int k = 0; k < cc.length; k++) {
                System.err.println("Pico clock scan C" + cc[k].id + ": " + count[k] +
                    " unique completed K0 frames in " + seconds + " s");
                if (count[k] < seconds * 15)
                    throw new IllegalStateException("C" + cc[k].id + ": low clock-scan rate; tracking asleep?");
            }
        } finally {
            for (Camera c : cc) if (c != null) c.close();
        }
    }

    public static void main(String[] args) {
        if (args.length >= 1 && "--clock-scan".equals(args[0])) {
            try {
                if (args.length > 2) throw new IllegalArgumentException("usage: --clock-scan [seconds]");
                scanClock(args.length == 2 ? Integer.parseInt(args[1]) : 20);
            } catch (Throwable e) {
                System.err.println("Pico clock scan FAILED: " + e);
                e.printStackTrace(System.err);
                System.exit(3);
            }
            return;
        }
        if (args.length == 1 && "--clock".equals(args[0])) {
            try {
                probeClock();
            } catch (Throwable e) {
                System.err.println("Pico clock probe FAILED: " + e);
                e.printStackTrace(System.err);
                System.exit(3);
            }
            return;
        }
        if (args.length == 1 && "--probe".equals(args[0])) {
            try {
                probe();
            } catch (Throwable e) {
                System.err.println("Pico Binder probe FAILED: " + e);
                e.printStackTrace(System.err);
                System.exit(3);
            }
            return;
        }
        Camera[] cameras = new Camera[4];
        try {
            IBinder svc = getService();
            if (svc == null || !"pvr.ITrackingService".equals(svc.getInterfaceDescriptor()))
                throw new IllegalStateException("pvr.ITrackingService unavailable");
            for (int i = 0; i < cameras.length; i++)
                cameras[i] = new Camera(svc, "pvr.ITrackingService", CAMERAS[i], SENSORS[i]);
            DataOutputStream output = new DataOutputStream(new BufferedOutputStream(System.out, 131072));
            long lastFrame = System.nanoTime();
            while (true) {
                int count = 0;
                for (Camera c : cameras) count += c.poll(output);
                long now = System.nanoTime();
                if (count != 0) lastFrame = now;
                if (now - lastFrame > MAX_NS_GAP)
                    throw new IllegalStateException("no K0 frames for 2s (tracking sleeping?)");
                Thread.sleep(5);
            }
        } catch (Throwable e) {
            System.err.println("PicoFrameReader: " + e);
            e.printStackTrace(System.err);
            System.exit(2);
        } finally {
            for (Camera c : cameras) if (c != null) c.close();
        }
    }
}
