import random
from typing import List, Optional, Dict


class Die:
    def __init__(self, faces: int, weights: Optional[List[float]] = None, seed: Optional[int] = None):
        """
        A die with a specified number of faces and optional weights for non-uniform probabilities.

        Args:
            faces: Number of faces (e.g., 6 for a d6).
            weights: Optional list of probabilities for each face (must sum to 1 if provided).
            seed: Optional random seed for reproducibility.
        """
        if faces < 1:
            raise ValueError("Die must have at least one face")
        self.faces = faces
        self.weights = weights if weights else [1.0 / faces] * faces
        if len(self.weights) != faces:
            raise ValueError("Weights length must match number of faces")
        if seed is not None:
            random.seed(seed)

    def roll(self, success_threshold: Optional[int] = None) -> tuple[int, bool]:
        """
        Roll the die and determine if the roll succeeds based on a threshold.

        Args:
            success_threshold: If provided, roll succeeds if value >= threshold.

        Returns:
            Tuple of (rolled value, success boolean).
        """
        if success_threshold is not None and (success_threshold < 1 or success_threshold > self.faces):
            raise ValueError(f"Success threshold must be between 1 and {self.faces}")

        value = random.choices(range(1, self.faces + 1), weights=self.weights, k=1)[0]
        success = value >= success_threshold if success_threshold is not None else True
        return value, success


class DiceBag:
    def __init__(self):
        """A collection of dice, accessible by key (e.g., 'd6', 'd20')."""
        self.dice: Dict[str, Die] = {}
        # Default dice for common use cases
        self.add_die("d6", Die(6))  # Standard 6-sided die
        self.add_die("d20", Die(20))  # 20-sided die for complex outcomes
        self.add_die("d100", Die(100))  # Percentile die

    def add_die(self, key: str, die: Die):
        """Add a die to the bag with a unique key."""
        self.dice[key] = die

    def roll(self, die_key: str, success_threshold: Optional[int] = None) -> tuple[int, bool]:
        """
        Roll a die by its key.

        Args:
            die_key: Key of the die to roll (e.g., 'd6').
            success_threshold: Optional threshold for success.

        Returns:
            Tuple of (rolled value, success boolean).
        """
        die = self.dice.get(die_key)
        if not die:
            raise ValueError(f"No die found with key '{die_key}'")
        return die.roll(success_threshold)