"""Read-only HMD identity check for PICO Connect -> SteamVR integration.

Requires: python -m pip install openvr
Run with SteamVR and a wirelessly streamed Pico 4 Pro active.
Prints only device model/driver properties, not the serial number or raw poses.
"""
import sys


def main():
    try:
        import openvr
    except ImportError as exc:
        raise SystemExit("Missing OpenVR Python binding: python -m pip install openvr") from exc

    try:
        vr = openvr.init(openvr.VRApplication_Background)
    except Exception as exc:
        raise SystemExit(f"SteamVR OpenVR unavailable: {exc}") from exc

    try:
        found = False
        properties = (
            "Prop_TrackingSystemName_String",
            "Prop_ActualTrackingSystemName_String",
            "Prop_ModelNumber_String",
            "Prop_RenderModelName_String",
            "Prop_ManufacturerName_String",
            "Prop_RegisteredDeviceType_String",
        )
        for device in range(openvr.k_unMaxTrackedDeviceCount):
            if vr.getTrackedDeviceClass(device) != openvr.TrackedDeviceClass_HMD:
                continue
            found = True
            print(f"HMD_INDEX={device}")
            for name in properties:
                prop = getattr(openvr, name, None)
                if prop is None:
                    print(f"{name}=<not supported by Python OpenVR package>")
                    continue
                try:
                    value = vr.getStringTrackedDeviceProperty(device, prop)
                except Exception as exc:
                    value = f"<unavailable: {exc}>"
                print(f"{name}={value}")
        if not found:
            print("No active SteamVR HMD. Start the Pico 4 Pro streamer and SteamVR, then retry.")
            return 2
        return 0
    finally:
        openvr.shutdown()


if __name__ == "__main__":
    sys.exit(main())
