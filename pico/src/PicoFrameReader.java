import android.os.IBinder;
import android.os.Parcel;
import android.os.SharedMemory;
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

    private static final class Camera implements AutoCloseable {
        final int id;
        final SharedMemory shm;
        final ByteBuffer view;
        final byte[] pixels = new byte[PIXELS];
        long lastSequence;

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
                reply.readException();
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
                int exposure = view.getInt(base + 110);
                if (exposure != 4)
                    throw new IllegalStateException("C" + id + ": K0 exposure changed to " + exposure);
                ByteBuffer frame = view.duplicate();
                frame.position(base + PIXEL_OFFSET);
                frame.get(pixels, 0, PIXELS);
                long readNs = System.nanoTime();
                if (view.getInt(12) != idx || view.getLong(base + 146) != next ||
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

    public static void main(String[] args) {
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
