import time
from enum import Enum


class EasingType(Enum):
    EASE_IN_QUAD = "ease_in_quad"
    EASE_OUT_QUAD = "ease_out_quad"
    EASE_IN_OUT_QUAD = "ease_in_out_quad"
    EASE_IN_CUBIC = "ease_in_cubic"
    EASE_OUT_CUBIC = "ease_out_cubic"
    EASE_IN_OUT_CUBIC = "ease_in_out_cubic"


class Tween:
    def __init__(
        self,
        target,
        duration,
        on_finish: callable = None,
        motion: EasingType | str = EasingType.EASE_IN_OUT_CUBIC,
        **kwargs,
    ):
        self.motion = motion.value if isinstance(motion, EasingType) else motion
        self.target = target
        self.duration = duration if duration is not None else 1.0
        # self.type = type # todo: implement
        self.on_finish = on_finish
        self.kwargs = kwargs
        self.start_time = None
        self.end_time = None
        self._is_running = False

    def start(self):
        self.start_time = time.time()
        self.end_time = self.start_time + self.duration
        self.progress = 0
        self._is_running = True

    def stop(self):
        self._is_running = False

    def update(self):
        if not self._is_running:
            return

        if time.time() > self.end_time:
            self.stop()
            return

        self._update()

    def is_finished(self):
        return not self._is_running

    def _update(self):
        self.progress = (time.time() - self.start_time) / self.duration
        # if self.kwargs.get("tween_property"):
        #     setattr(self.target, self.kwargs['tween_property'], lerp(self.kwargs['from_'], self.kwargs['to_'], self.progress))
        if self.kwargs.get("tween_property"):
            if self.kwargs["from_"] is None:
                self.kwargs["from_"] = getattr(
                    self.target, self.kwargs["tween_property"]
                )
            setattr(
                self.target,
                self.kwargs["tween_property"],
                Tween.lerp(
                    self.kwargs["from_"],
                    self.kwargs["to_"],
                    getattr(self, self.motion)(self.progress),
                ),
            )

    def __repr__(self):
        return f"Tween(target={self.target}, duration={self.duration}, kwargs={self.kwargs})"

    @staticmethod
    def lerp(a, b, t):
        return a + (b - a) * t

    @staticmethod
    def ease_in_quad(t):
        return t * t

    @staticmethod
    def ease_out_quad(t):
        return t * (2 - t)

    @staticmethod
    def ease_in_out_quad(t):
        if t < 0.5:
            return 2 * t * t
        else:
            return -1 + (4 - 2 * t) * t

    @staticmethod
    def ease_in_cubic(t):
        return t * t * t

    @staticmethod
    def ease_out_cubic(t):
        return 1 + (t - 1) * t * t

    @staticmethod
    def ease_in_out_cubic(t):
        if t < 0.5:
            return 4 * t * t * t
        else:
            return (t - 1) * (2 * t - 2) * (2 * t - 2) + 1


class TweenManager:
    def __init__(self):
        self.tweens = []
        self.motion = EasingType.EASE_IN_OUT_CUBIC

    def kill_tweens(self, target, tween_property=None):
        """Remove all tweens for a target, optionally filtered by property"""
        tweens_to_remove = []
        for tween in self.tweens:
            if tween.target == target:
                if (
                    tween_property is None
                    or tween.kwargs.get("tween_property") == tween_property
                ):
                    # print(f"[TweenManager] KILLING tween: {tween}")
                    tween.stop()
                    tweens_to_remove.append(tween)

        for tween in tweens_to_remove:
            self.tweens.remove(tween)

    def add_tween(
        self,
        target,
        tween_property,
        from_=None,
        to_=None,
        duration=None,
        on_finish: callable = None,
        kill_existing=True,
    ):
        # Kill existing tweens on the same target+property to avoid conflicts
        if kill_existing:
            self.kill_tweens(target, tween_property)

        tween = Tween(
            target,
            duration,
            on_finish=on_finish,
            motion=self.motion,
            tween_property=tween_property,
            from_=from_,
            to_=to_,
        )
        tween.start()
        self.tweens.append(tween)

    def set_tween_motion_method(self, motion: EasingType | str):
        self.motion = motion

    def update(self):
        for tween in self.tweens:
            tween.update()
            if tween.is_finished():
                # print(f"[TweenManager] Tween FINISHED: {tween}")
                if tween.on_finish:
                    # print(f"[TweenManager] Calling on_finish for {tween}")
                    tween.on_finish.__call__()
                self.tweens.remove(tween)

    def is_empty(self) -> bool:
        return len(self.tweens) == 0
