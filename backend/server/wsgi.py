from .app import app, init_scheduler, register_base_path_aliases

register_base_path_aliases()
init_scheduler()


__all__ = ["app"]
