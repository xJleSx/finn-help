from __future__ import annotations

import abc
import asyncio
import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HookPriority(IntEnum):
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100


@dataclass
class Hook:
    name: str
    handlers: list[tuple[HookPriority, Callable[..., Any]]] = field(default_factory=list)

    def add(self, handler: Callable[..., Any], priority: HookPriority = HookPriority.NORMAL) -> None:
        self.handlers.append((priority, handler))
        self.handlers.sort(key=lambda x: x[0].value, reverse=True)

    def remove(self, handler: Callable[..., Any]) -> None:
        self.handlers = [(p, h) for p, h in self.handlers if h is not handler]

    def trigger(self, *args: Any, **kwargs: Any) -> list[Any]:
        results = []
        for priority, handler in self.handlers:
            try:
                result = handler(*args, **kwargs)
                results.append(result)
            except Exception:
                logger.exception("Hook handler %s failed", handler.__name__)
        return results

    async def trigger_async(self, *args: Any, **kwargs: Any) -> list[Any]:
        results = []
        for priority, handler in self.handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(*args, **kwargs)
                else:
                    result = handler(*args, **kwargs)
                results.append(result)
            except Exception:
                logger.exception("Async hook handler %s failed", handler.__name__)
        return results


def hook(name: str, priority: HookPriority = HookPriority.NORMAL) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        hooks = getattr(func, "_hooks", [])
        hooks.append((name, priority))
        func._hooks = hooks
        return func
    return decorator


class PluginBase(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def version(self) -> str: ...

    def on_load(self, manager: PluginManager) -> None:
        pass

    def on_unload(self, manager: PluginManager) -> None:
        pass


class PluginManager:
    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}
        self._hooks: dict[str, Hook] = {}
        self._package = "src.plugins"

    @property
    def package(self) -> str:
        return self._package

    @package.setter
    def package(self, value: str) -> None:
        self._package = value

    def register_hook(self, name: str) -> Hook:
        if name not in self._hooks:
            self._hooks[name] = Hook(name=name)
        return self._hooks[name]

    def get_hook(self, name: str) -> Hook | None:
        return self._hooks.get(name)

    def trigger(self, name: str, *args: Any, **kwargs: Any) -> list[Any]:
        hook = self._hooks.get(name)
        if hook is None:
            return []
        return hook.trigger(*args, **kwargs)

    async def trigger_async(self, name: str, *args: Any, **kwargs: Any) -> list[Any]:
        hook = self._hooks.get(name)
        if hook is None:
            return []
        return await hook.trigger_async(*args, **kwargs)

    def register_plugin(self, plugin: PluginBase) -> None:
        self._plugins[plugin.name] = plugin
        self._scan_plugin_hooks(plugin)
        try:
            plugin.on_load(self)
        except Exception:
            logger.exception("Plugin %s on_load failed", plugin.name)
        logger.info("Plugin registered: %s v%s", plugin.name, plugin.version)

    def unregister_plugin(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin:
            try:
                plugin.on_unload(self)
            except Exception:
                logger.exception("Plugin %s on_unload failed", name)
            logger.info("Plugin unregistered: %s", name)

    def get_plugin(self, name: str) -> PluginBase | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginBase]:
        return list(self._plugins.values())

    def discover_plugins(self, package: str | None = None) -> None:
        pkg_name = package or self._package
        try:
            pkg = importlib.import_module(pkg_name)
        except ImportError:
            logger.warning("Plugin package %s not found", pkg_name)
            return
        for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            try:
                full_name = f"{pkg_name}.{modname}"
                mod = importlib.import_module(full_name)
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if (issubclass(obj, PluginBase) and obj is not PluginBase
                            and not inspect.isabstract(obj)):
                        plugin_instance = obj()
                        self.register_plugin(plugin_instance)
                        logger.info("Discovered and registered plugin %s from %s", name, full_name)
            except Exception:
                logger.exception("Failed to load plugin module %s", modname)

    def _scan_plugin_hooks(self, plugin: PluginBase) -> None:
        for name, method in inspect.getmembers(plugin, inspect.ismethod):
            if hasattr(method, "_hooks"):
                for hook_name, priority in method._hooks:
                    h = self.register_hook(hook_name)
                    h.add(method, priority)
                    logger.debug("Registered hook %s for %s.%s", hook_name, plugin.name, method.__name__)

    def clear(self) -> None:
        self._plugins.clear()
        self._hooks.clear()


plugin_manager = PluginManager()
