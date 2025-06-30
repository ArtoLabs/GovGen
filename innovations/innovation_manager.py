import random
from typing import Optional, Tuple
from innovations.innovation import InnovationPool, ALL_INNOVATIONS
from innovations.innovation_map import ROLE_INNOVATION_MAP
from utils.messages import Messages

class InnovationManager:
    def __init__(self, government: 'core.government.Government'):
        self.government = government

    def add_to_research_queue(self, innovation_name: str) -> bool:
        """Add an innovation to the research queue."""
        discoverable = [i.name for i in self.government.innovation_pool.get_discoverable()]
        if innovation_name in discoverable and innovation_name not in self.government.research_queue:
            self.government.research_queue.append(innovation_name)
            return True
        return False

    def remove_from_research_queue(self, innovation_name: str) -> bool:
        """Remove an innovation from the research queue."""
        if innovation_name in self.government.research_queue:
            self.government.research_queue.remove(innovation_name)
            return True
        return False

    def process_research_queue(self):
        """Process the research queue for innovations."""
        queue_copy = list(self.government.research_queue)
        for innovation_name in queue_copy:
            innovation = ALL_INNOVATIONS.get(innovation_name)
            if not innovation:
                Messages.add(f"Invalid innovation {innovation_name} in queue; skipping.")
                self.government.research_queue.remove(innovation_name)
                continue
            if innovation_name in self.government.innovation_pool.discovered:
                Messages.add(f"{innovation_name} is already discovered; skipping.")
                self.government.research_queue.remove(innovation_name)
                continue
            if self.government.innovation_pool.points >= innovation.cost:
                self.government.innovation_pool.spend_points(innovation.cost)
                self.government.innovation_pool.discovered.add(innovation_name)
                Messages.add(f"Discovered {innovation_name} from research queue (Cost: {innovation.cost}).")
                self.government.research_queue.remove(innovation_name)
            else:
                Messages.add(
                    f"Insufficient points ({self.government.innovation_pool.points}) to discover {innovation_name} (Cost: {innovation.cost})."
                )

    def discover_random_innovation(self) -> Tuple[Optional[str], str]:
        """Attempt to discover a random innovation with a dice roll."""
        roll_value, success = self.government.dice_bag.roll("d6", success_threshold=6)
        if not success:
            return None, f"Random innovation roll: {roll_value}/6 (needed 6). No innovation discovered."
        active_base_roles = set()
        for titled_role, holders in self.government.assignments.items():
            if holders:
                active_base_roles.update(self.government.government_type.role_mappings.get(titled_role, []))
        discoverable = self.government.innovation_pool.get_discoverable()
        affordable = [
            innov for innov in discoverable
            if innov.cost <= self.government.innovation_pool.points and
               any(innov.name in role_innovations for role, role_innovations in ROLE_INNOVATION_MAP.items()
                   if role in active_base_roles)
        ]
        if not affordable:
            return None, f"Random innovation roll: {roll_value}/6. No affordable innovations available for active roles."
        innovation = random.choice(affordable)
        self.government.innovation_pool.discovered.add(innovation.name)
        self.government.innovation_pool.points -= innovation.cost
        return innovation.name, f"Random innovation roll: {roll_value}/6. Discovered {innovation.name} (Cost: {innovation.cost})."

    def process_turn(self):
        """Process innovation-related actions for a turn."""
        self.process_research_queue()
        if not self.government.research_queue:
            innovation, message = self.discover_random_innovation()
            Messages.add(message)