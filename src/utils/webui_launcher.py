# Thin wrapper so legacy imports go through the real launcher impl.
def launch_webui_safely(*args, **kwargs):
    from .webui_discovery import launch_webui_safely as _launch_webui

    return _launch_webui(*args, **kwargs)
