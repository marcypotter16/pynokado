"""
Tween Animation System

A lightweight tweening/easing animation library for smooth interpolation between values.
Supports multiple easing functions and can animate any numeric property of any object.

Example usage:
    # Animate a pygame rect position
    rect = pygame.Rect(0, 0, 50, 50)
    tween = Tween(rect, 2.0, tween_property='x', from_=0, to_=100)
    tween.start()

    # Or use the manager for automatic handling
    manager = TweenManager()
    manager.add_tween(rect, 'x', 0, 100, 2.0)
"""

import time

class Tween:
    """
    A single tween animation that interpolates a property of a target object over time.

    The Tween class handles the animation of a single property on a target object,
    applying various easing functions to create smooth transitions.

    Attributes:
        target: The object whose property will be animated
        duration (float): Animation duration in seconds
        motion (str): Name of the easing function to use
        on_finish (callable): Optional callback when animation completes
        kwargs: Additional parameters including tween_property, from_, to_
        start_time (float): When the animation started (timestamp)
        end_time (float): When the animation should end (timestamp)
        progress (float): Current progress from 0.0 to 1.0
        _is_running (bool): Whether the animation is currently active
    """
    def __init__(self, target, duration, on_finish: callable = None, motion: str = "ease_in_out_cubic", **kwargs):
        """
        Initialize a new tween animation.

        Args:
            target: The object to animate (must have the property specified in kwargs)
            duration (float): Animation duration in seconds
            on_finish (callable, optional): Function to call when animation completes
            motion (str): Easing function name (default: "ease_in_out_cubic")
            **kwargs: Additional parameters:
                - tween_property (str): Name of the property to animate
                - from_ (numeric): Starting value
                - to_ (numeric): Target value

        Example:
            tween = Tween(my_sprite, 1.5, tween_property='x', from_=0, to_=100)
        """
        self.motion = motion
        self.target = target
        self.duration = duration
        self.on_finish = on_finish
        self.kwargs = kwargs
        self.start_time = None
        self.end_time = None
        self._is_running = False
        self.progress = 0.0

    def start(self):
        """
        Start the tween animation.

        Records the current time as the start time and calculates the end time.
        Sets the animation state to running.
        """
        self.start_time = time.time()
        self.end_time = self.start_time + self.duration
        self.progress = 0
        self._is_running = True

    def stop(self):
        """
        Stop the tween animation.

        Marks the animation as no longer running. Does not reset progress.
        """
        self._is_running = False

    def update(self):
        """
        Update the tween animation for the current frame.

        Should be called every frame in your game loop. Checks if the animation
        is complete and updates the target property if still running.
        """
        if not self._is_running:
            return

        # Check if animation duration has elapsed
        if time.time() > self.end_time:
            self.stop()
            return

        self._update()

    def is_finished(self):
        """
        Check if the tween animation has completed.

        Returns:
            bool: True if the animation is finished, False otherwise
        """
        return not self._is_running

    def _update(self):
        """
        Internal update method that calculates and applies the interpolated value.

        Calculates the current progress (0.0 to 1.0), applies the easing function,
        and updates the target object's property with the interpolated value.
        """
        # Calculate linear progress from 0.0 to 1.0
        self.progress = (time.time() - self.start_time) / self.duration

        # Apply tween if property is specified
        if self.kwargs.get("tween_property"):
            # Get the easing function by name and apply it to progress
            eased_progress = getattr(self, self.motion)(self.progress)

            # Calculate interpolated value and set it on the target
            interpolated_value = Tween.lerp(
                self.kwargs['from_'],
                self.kwargs['to_'],
                eased_progress
            )
            setattr(self.target, self.kwargs['tween_property'], interpolated_value)

    def __repr__(self):
        return f'Tween(target={self.target}, duration={self.duration}, kwargs={self.kwargs})'
    
    @staticmethod
    def lerp(a, b, t):
        """
        Linear interpolation between two values.

        Args:
            a (numeric): Start value
            b (numeric): End value
            t (float): Interpolation factor (0.0 to 1.0)

        Returns:
            numeric: Interpolated value between a and b
        """
        return a + (b - a) * t

    @staticmethod
    def ease_in_quad(t):
        """
        Quadratic ease-in function.

        Args:
            t (float): Progress value (0.0 to 1.0)

        Returns:
            float: Eased progress value
        """
        return t * t

    @staticmethod
    def ease_out_quad(t):
        """
        Quadratic ease-out function.

        Args:
            t (float): Progress value (0.0 to 1.0)

        Returns:
            float: Eased progress value
        """
        return t * (2 - t)

    @staticmethod
    def ease_in_out_quad(t):
        """
        Quadratic ease-in-out function.

        Args:
            t (float): Progress value (0.0 to 1.0)

        Returns:
            float: Eased progress value
        """
        if t < 0.5:
            return 2 * t * t
        else:
            return -1 + (4 - 2 * t) * t
        
    @staticmethod
    def ease_in_cubic(t):
        """
        Cubic ease-in function.

        Args:
            t (float): Progress value (0.0 to 1.0)

        Returns:
            float: Eased progress value
        """
        return t * t * t

    @staticmethod
    def ease_out_cubic(t):
        """
        Cubic ease-out function.

        Args:
            t (float): Progress value (0.0 to 1.0)

        Returns:
            float: Eased progress value
        """
        return 1 + (t - 1) * t * t

    @staticmethod
    def ease_in_out_cubic(t):
        """
        Cubic ease-in-out function. Default easing function.

        Args:
            t (float): Progress value (0.0 to 1.0)

        Returns:
            float: Eased progress value
        """
        if t < 0.5:
            return 4 * t * t * t
        else:
            return (t - 1) * (2 * t - 2) * (2 * t - 2) + 1
    
class TweenManager:
    """
    Manages multiple tween animations and handles their lifecycle.

    The TweenManager provides a convenient way to handle multiple tweens,
    automatically starting them when added and cleaning them up when finished.
    It should be updated once per frame in your game loop.

    Attributes:
        tweens (list): List of active Tween objects

    Example:
        manager = TweenManager()
        manager.add_tween(sprite, 'x', 0, 100, 2.0)

        # In game loop:
        manager.update()
    """
    def __init__(self):
        """
        Initialize a new TweenManager.

        Creates an empty list to store active tweens.
        """
        self.tweens = []

    def add_tween(self, target, tween_property, from_, to_, duration, on_finish: callable = None, motion: str = "ease_in_out_cubic"):
        """
        Create and start a new tween animation.

        Args:
            target: The object to animate
            tween_property (str): Name of the property to animate
            from_ (numeric): Starting value
            to_ (numeric): Target value
            duration (float): Animation duration in seconds
            on_finish (callable, optional): Function to call when animation completes
            motion (str): Easing function name (default: "ease_in_out_cubic")

        Example:
            # Animate sprite position
            manager.add_tween(sprite, 'x', 0, 100, 1.5, motion="ease_out_quad")

            # Animate with callback
            manager.add_tween(sprite, 'alpha', 255, 0, 1.0, on_finish=sprite.hide)
        """
        # Create the tween with all parameters
        tween = Tween(target, duration, on_finish=on_finish, motion=motion,
                     tween_property=tween_property, from_=from_, to_=to_)
        # Start immediately and add to active tweens list
        tween.start()
        self.tweens.append(tween)

    def update(self):
        """
        Update all active tweens.

        Should be called once per frame in your game loop. Updates all tweens,
        calls completion callbacks, and removes finished tweens from the list.

        Note: Modifies the tweens list during iteration, so we iterate over
        a copy to avoid issues.
        """
        # Iterate over a copy to safely remove items during iteration
        for tween in self.tweens[:]:
            tween.update()
            if tween.is_finished():
                # Call completion callback if provided
                if tween.on_finish:
                    tween.on_finish()
                # Remove completed tween from active list
                self.tweens.remove(tween)

    def is_empty(self) -> bool:
        """
        Check if there are any active tweens.

        Returns:
            bool: True if no tweens are running, False otherwise
        """
        return len(self.tweens) == 0