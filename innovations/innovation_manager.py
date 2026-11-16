import random
from typing import Optional, Tuple
from innovations.innovation import InnovationPool, ALL_INNOVATIONS
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

    def advance_research(self, income: float):
        """One day of research. The day's income flows into the innovation at the front of the queue,
        and savings in the stockpile can add at most as much again, so research takes real time.
        With nothing queued, income goes to the stockpile."""
        gov = self.government
        pool, queue = gov.innovation_pool, gov.research_queue
        self._drop_finished()
        if not queue:
            pool.add_points(income)
            return
        boost = min(pool.points, income)
        pool.points -= boost
        gov.research_progress += income + boost
        while queue and gov.research_progress >= ALL_INNOVATIONS[queue[0]].cost:
            innovation = ALL_INNOVATIONS[queue.pop(0)]
            gov.research_progress -= innovation.cost
            pool.discovered.add(innovation.name)
            Messages.add(f"Discovered {innovation.name} (Cost: {innovation.cost}).")
            self._drop_finished()
        if not queue:  # leftover progress returns to the stockpile
            pool.add_points(gov.research_progress)
            gov.research_progress = 0

    def _drop_finished(self):
        queue, discovered = self.government.research_queue, self.government.innovation_pool.discovered
        while queue and (queue[0] not in ALL_INNOVATIONS or queue[0] in discovered):
            queue.pop(0)

    def research_progress(self):
        """(innovation, points put into it so far, cost) for the item being researched, or None."""
        queue = self.government.research_queue
        if not queue or queue[0] not in ALL_INNOVATIONS:
            return None
        return queue[0], int(self.government.research_progress), ALL_INNOVATIONS[queue[0]].cost

    def discover_random_innovation(self) -> Tuple[Optional[str], str]:
        """Attempt to discover a random innovation with a dice roll."""
        roll_value, success = self.government.dice_bag.roll("d6", success_threshold=6)
        if not success:
            return None, f"Random innovation roll: {roll_value}/6 (needed 6). No innovation discovered."
        active_interfaces = self.government.active_interfaces()
        affordable = [
            innov for innov in self.government.innovation_pool.get_discoverable()
            if innov.cost <= self.government.innovation_pool.points and innov.interface in active_interfaces
        ]
        if not affordable:
            return None, f"Random innovation roll: {roll_value}/6. No affordable innovations available for active roles."
        innovation = random.choice(affordable)
        self.government.innovation_pool.discovered.add(innovation.name)
        self.government.innovation_pool.points -= innovation.cost
        return innovation.name, f"Random innovation roll: {roll_value}/6. Discovered {innovation.name} (Cost: {innovation.cost})."

    def yearly_random_discovery(self):
        """Once a year, with nothing queued, the society may stumble on something by chance."""
        if not self.government.research_queue:
            innovation, message = self.discover_random_innovation()
            Messages.add(message, important=innovation is not None)