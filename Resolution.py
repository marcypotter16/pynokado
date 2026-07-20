# test_dpi_pygame.py
import sys


def set_dpi_awareness():
    """Try to make the process DPI-aware on Windows (best-effort)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        user32 = ctypes.windll.user32
        # Try modern per-monitor v2 (Windows 10+)
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            ):
                print("SetProcessDpiAwarenessContext(per-monitor v2) OK")
                return
        except Exception:
            pass
        # Try SetProcessDpiAwareness from shcore (Windows 8.1+)
        try:
            shcore = ctypes.windll.shcore
            PROCESS_PER_MONITOR_DPI_AWARE = 2
            if shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
                print("SetProcessDpiAwareness(per-monitor) OK")
                return
        except Exception:
            pass
        # Fallback: legacy API
        try:
            if user32.SetProcessDPIAware():
                print("SetProcessDPIAware() OK")
                return
        except Exception:
            pass
    except Exception as e:
        print("Could not set DPI awareness:", e)


# NOTE: DPI awareness is opt-in. Import this module freely without side effects;
# call set_dpi_awareness() explicitly (before importing pygame) if you want it.
# It's off by default because per-monitor awareness makes window sizes swing when
# moving between different-DPI screens, which is a pain during development.

if __name__ == "__main__":
    set_dpi_awareness()
    import pygame

    pygame.init()

    # create the window at the target resolution
    TARGET = (1920, 1080)
    screen = pygame.display.set_mode(TARGET)
    pygame.display.set_caption("DPI test")

    # print diagnostics to verify sizes
    info = pygame.display.Info()
    print(
        "pygame.display.Info(): current_w =",
        info.current_w,
        "current_h =",
        info.current_h,
    )
    surface_size = screen.get_size()
    print("Created surface size (logical):", surface_size)
    try:
        import ctypes

        hwnd = pygame.display.get_wm_info().get("window")
        if hwnd:
            user32 = ctypes.windll.user32
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            print(
                "Window rect (left, top, right, bottom):",
                rect.left,
                rect.top,
                rect.right,
                rect.bottom,
            )
            print(
                "Window physical size (pixels):",
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
    except Exception:
        pass

    # simple loop so window stays open
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
        screen.fill((50, 50, 50))
        pygame.display.flip()

    pygame.quit()
