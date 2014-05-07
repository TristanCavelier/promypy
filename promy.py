# -*- coding: utf-8 -*-

"""
A Promise A+ compatible library with cancellation and notification for python 2
or 3 with pyjsruntime.

Version 1.0.0

Copyright (c) 2014 Tristan Cavelier <t.cavelier@free.fr>
This program is free software. It comes without any warranty, to
the extent permitted by applicable law. You can redistribute it
and/or modify it under the terms of the Do What The Fuck You Want
To Public License, Version 2, as published by Sam Hocevar. See
the COPYING file for more details.
"""

from jsruntime import set_timeout
from inspect import isfunction

def _empty_function(*args, **kwargs): pass

class CancelException(Exception): pass

######################################################################

def _on(obj, tipe, listener):
    if getattr(obj, "_events", None) is None:
        obj._events = {}
    if obj._events.get(tipe) is None:
        obj._events[tipe] = listener
    elif isfunction(obj._events[tipe]):
        obj._events[tipe] = [obj._events[tipe], listener]
    elif isinstance(obj._events[tipe], list):
        obj._events[tipe].append(listener)
    return obj

def _emit(obj, tipe, *lyst, **kwargs):
    if getattr(obj, "_events", None) is None or obj._events.get(tipe) is None:
        return obj
    funs = obj._events[tipe]
    if isfunction(funs):
        # Enable compatibility with EventEmitter, the event listener list can be
        # a listener
        funs(*lyst, **kwargs)
        return obj
    if isinstance(funs, list):
        funs = [x for x in funs]
        for fun in funs:
            fun(*lyst, **kwargs)
    return obj

def _async(fn, *lyst, **kwargs):
    return set_timeout(fn, 0, *lyst, **kwargs)

######################################################################

def _fulfill(promise, value):
    if promise._settled: return
    promise._fulfilled = True
    promise._settled = True
    promise._fulfillment_value = value
    _async(lambda: _emit(promise, "promise:resolved", {"detail": value}))

def _reject(promise, value):
    if promise._settled: return
    promise._rejected = True
    promise._settled = True
    promise._rejected_reason = value
    _async(lambda: _emit(promise, "promise:rejected", {"detail": value}))

def _notify(promise, value):
    if promise._settled: return
    _async(lambda: _emit(promise, "promise:notified", {"detail": value}))

def _cancel(promise):
    value = CancelException("Cancelled")
    if promise._settled: return
    promise._rejected = True
    promise._settled = True
    promise._rejected_reason = value
    _emit(promise, "promise:cancelled", {"detail": None})
    _async(lambda: _emit(promise, "promise:rejected", {"detail": value}))

def _resolve(promise, value):
    # The _handle_thenable cannot operate with promise === value, so in this
    # case, the promise is fulfilled with itself as fulfillment value.
    if promise is value or not _handle_thenable(promise, value):
        _fulfill(promise, value)

def _handle_thenable(promise, value):
    resolved = [False]
    try:
        if promise is value:
            raise TypeError("A promise callback cannot " +
                            "return that same promise.")
        if isfunction(getattr(value, "then", None)):
            # use then attr or then dict property?
            def on_cancel():
                try:
                    if isfunction(getattr(value, "cancel", None)):
                        value.cancel()
                except Exception: pass
            _on(promise, "promise:cancelled", on_cancel)
            def on_done(val):
                if resolved[0]:
                    return True
                resolved[0] = True
                if value is not val:
                    _resolve(promise, val)
                else:
                    _fulfill(promise, val)
            def on_fail(val):
                if resolved[0]:
                    return True
                resolved[0] = True
                _reject(promise, val)
            def on_progress(notification):
                _notify(promise, notification)
            value.then(on_done, on_fail, on_progress)
            return True
    except Exception as error:
        _reject(promise, error)
        return True
    return False

def _invoke_callback(resolver, promise, callback, event):
    succeeded = False
    failed = False
    error = None
    value = None
    if promise._settled: return
    has_callback = isfunction(callback)
    if has_callback:
        try:
            value = callback(event["detail"])
            succeeded = True
        except Exception as e:
            failed = True
            error = e
    else:
        value = event["detail"]
        succeded = True
    if _handle_thenable(promise, value): return
    if has_callback and succeeded:
        _resolve(promise, value)
    elif failed:
        _reject(promise, error)
    else:
        resolver(promise, value)

def _invoke_notify_callback(promise, callback, event):
    if promise._settled: return
    if isfunction(callback):
        try:
            value = callback(event["detail"])
        except Exception:
            # stop propagation
            return
        _notify(promise, value)
    else:
        _notify(promise, event["detail"])

######################################################################

class Promise(object):
    def __init__(self, executor, canceller=None):
        self._rejected = False
        self._fulfilled = False
        self._rejected_reason = None
        self._fulfillment_value = None
        self._settled = False
        if not isfunction(executor):
            raise TypeError("Promise(executor[, canceller]): " +
                            "executor must be a function")
        if isfunction(canceller):
            def tryer():
                try: canceller()
                except Exception: pass
            _on(self, "promise:cancelled", tryer)
        def resolve(answer):
            return _resolve(self, answer)
        def reject(reason):
            return _reject(self, reason)
        def notify(notification):
            return _notify(self, notification)
        try:
            executor(resolve, reject, notify)
        except Exception as e:
            _reject(self, e)

    def then(self, done=None, fail=None, progress=None):
        then_promise = Promise(_empty_function)
        if self._settled:
            if self._fulfilled:
                def on_done():
                    _invoke_callback(_resolve, then_promise, done, {
                        "detail": self._fulfillment_value
                    })
                _async(on_done)
            if self._rejected:
                def on_fail():
                    _invoke_callback(_reject, then_promise, fail, {
                        "detail": self._rejected_reason
                    })
                _async(on_fail)
        else:
            def on_done(event):
                _invoke_callback(_resolve, then_promise, done, event)
            _on(self, "promise:resolved", on_done)
            def on_fail(event):
                _invoke_callback(_reject, then_promise, fail, event)
            _on(self, "promise:rejected", on_fail)
        def on_progress(event):
            _invoke_notify_callback(then_promise, progress, event)
        _on(self, "promise:notified", on_progress)
        return then_promise

    def catch(self, fail=None):
        return self.then(None, fail)

    def progress(self, progress=None):
        return self.then(None, None, progress)

    def cancel(self):
        if not self._settled: _cancel(self)
        return self
