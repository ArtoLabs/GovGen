import os
from typing import List, Tuple, Callable
from government import Government
from player import players, get_player_by_name
from interfaces import initialize_interfaces, get_interface
from government_types import get_available_government_types, get_government_type
from innovation import INNOVATIONS
from messages import Messages
from utils import choose_from_list

class Simulation:
    def __init__(self):
        self.government = Government()
        self.current_year = 0
        self.current_player_index = 0
        self.players = players
        self.active_interface = None  # Tracks the current role interface
        self.running = True  # Controls the main loop
        for player in self.players:
            self.government.add_player(player)
        self.government.initialize()
        initialize_interfaces(self.government)

        # Define general command methods
        self.general_commands: List[Tuple[str, str, Callable[[], None]]] = [
            ("list_players", "Show all players and their roles", self.do_list_players),
            ("list_roles", "Show available roles", self.do_list_roles),
            ("list_methods", "Show available selection methods for a role", self.do_list_methods),
            ("research", "Research a specific innovation", self.do_research),
            ("list_innovations", "Show all possible innovations", self.do_list_innovations),
            ("set_government_type", "Change the government type", self.do_set_government_type),
            ("end_turn", "End the current player's turn", self.do_end_turn),
            ("exit", "Exit the simulation", self.do_exit),
            ("open_role_interface", "Open a role interface", self.do_open_role_interface),
        ]

    def clear_screen(self):
        """Clear the console screen."""
        os.system('cls' if os.name == 'nt' else 'clear')

    # General command methods
    def do_list_players(self):
        for p in self.players:
            print(p)

    def do_list_roles(self):
        titled_roles = list(self.government.government_type.role_mappings.keys())
        print("Available Roles:", titled_roles or "None")

    def do_list_methods(self):
        role_id = input("Enter role key (e.g., chieftain): ").strip().lower()
        methods = self.government.get_available_selection_methods(role_id)
        print("Available Selection Methods:", [m.name for m in methods] or "None")

    def do_research(self):
        discoverable = self.government.innovation_pool.get_discoverable()
        if not discoverable:
            print("No discoverable innovations.")
            return
        # Use choose_from_list with a custom display function
        selected = choose_from_list(
            discoverable,
            "Select innovation to queue for research:",
            lambda i: f"{i.name} (Cost: {i.cost})"
        )
        if selected:
            if self.government.add_to_research_queue(selected.name):
                print(f"{selected.name} added to research queue (no points spent).")
            else:
                print(f"Cannot queue {selected.name} for research.")

    def do_list_innovations(self):
        print("All Possible Innovations:")
        discovered = set(i.name for i in self.government.innovation_pool.get_discovered())
        for innovation in INNOVATIONS.values():
            status = "Discovered" if innovation.name in discovered else "Not Discovered"
            print(f"{innovation.name} (Cost: {innovation.cost}) - {status}")

    def do_set_government_type(self):
        available_types = get_available_government_types(self.government.innovation_pool.discovered)
        if not available_types:
            print("No available government types.")
            return
        selected = choose_from_list(available_types, "Select government type:", lambda t: t.name)
        if selected:
            if self.government.set_government_type(selected.name.lower()):
                print(f"Government type changed to {selected.name}.")
            else:
                print("Failed to change government type.")

    # Usage in do_end_turn:
    def do_end_turn(self):
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        if self.current_player_index == 0:
            self.current_year += 1
            self.government.generate_innovation_points()
            Messages.add(
                f"Year {self.current_year} begins. Innovation Points: {self.government.innovation_pool.points}")
            self.government.process_research_queue()
            if not self.government.research_queue:
                new_innovation = self.government.discover_random_innovation()
                if new_innovation:
                    Messages.add(f"Queue empty. Randomly discovered {new_innovation}.")

    def do_exit(self):
        print("Exiting simulation.")
        self.running = False

    def do_open_role_interface(self):
        current_player = self.players[self.current_player_index]
        interfaces = self.government.get_player_interfaces(current_player)
        if not interfaces:
            print("You have no role interfaces available.")
            return
        selected = choose_from_list(
            interfaces,
            "Select role interface:",
            lambda i: i.role_key.capitalize()
        )
        if selected:
            self.active_interface = selected

    def do_close_interface(self):
        self.active_interface = None

    def get_general_menu(self, start_number: int = 1) -> Tuple[str, List[Tuple[int, Callable[[], None], str]]]:
        """Generate the general menu with dynamic numbering."""
        current_player = self.players[self.current_player_index]
        has_roles = bool(current_player.assigned_roles)
        menu_str = "General Commands:\n"
        menu_items = []
        number = start_number

        # Include all commands except open_role_interface if no roles
        for key, desc, action in self.general_commands:
            if key == "open_role_interface" and not has_roles:
                continue
            menu_str += f"  {number}: {desc}\n"
            menu_items.append((number, action, key))
            number += 1

        return menu_str, menu_items

    def get_prompt(self):
        # Get the current player using the index
        current_player = self.players[self.current_player_index]

        # Determine the roles held by the current player
        roles = [
            role_key
            for role_key, holders in self.government.assignments.items()
            if current_player in holders
        ]
        roles = list(dict.fromkeys(roles)) or ["None"]

        # Gather state information
        discovered = [i.name for i in self.government.innovation_pool.get_discovered()]
        state_info = (
            "__________________________________\n"
            f"Year {self.current_year} | Innovation Points: {self.government.innovation_pool.points}\n"
            f"Government Type: {self.government.government_type.name}\n"
            f"Discovered Innovations: {', '.join(discovered) or 'None'}\n"
            f"Research Queue: {', '.join(self.government.research_queue) or 'Empty'}\n"
            "__________________________________\n"
        )

        # Build the general menu
        general_menu, general_items = self.get_general_menu(start_number=1)
        menu_str = general_menu
        menu_items = general_items
        msg_str = Messages.to_str()
        Messages.clear()

        # Add submenu for active interface, if present
        submenu = ""
        if self.active_interface:
            submenu = (
                "__________________________________\n"
                f"{self.active_interface.role_key.capitalize()} Interface Commands:\n"
            )
            role_commands = self.active_interface.get_commands()
            number = len(general_items) + 1
            for cmd_key, cmd_desc in role_commands.items():
                action = lambda key=cmd_key: self.active_interface.execute_command(key)
                submenu += f"  {number}: {cmd_desc}\n"
                menu_items.append((number, action, cmd_key))
                number += 1
            submenu += f"  {number}: Close interface\n"
            menu_items.append((number, self.do_close_interface, "close_interface"))

        # Construct the final prompt
        prompt = f"\n{current_player.name} ({', '.join(roles)}) > "
        return msg_str + "\n" + state_info + menu_str + submenu + prompt, menu_items

    def run(self):
        """Run the simulation loop with a clean command-line interface."""
        self.clear_screen()
        Messages.add("Government Simulation Started")
        Messages.add(f"Players: {[p.name for p in self.players]}")
        Messages.add(f"Initial Year: {self.current_year}")

        while self.running:
            self.clear_screen()
            prompt, menu_items = self.get_prompt()
            command = input(prompt).strip().lower()

            try:
                num = int(command)
                for number, action, key in menu_items:
                    if number == num:
                        action()
                        if key not in ["end_turn", "exit"]:
                            input("Press Enter to continue...")
                        break
                else:
                    print("Invalid selection.")
            except ValueError:
                # Allow text commands as fallback
                for number, action, key in menu_items:
                    if command == key:
                        action()
                        if key not in ["end_turn", "exit"]:
                            input("Press Enter to continue...")
                        break
                else:
                    print("Unknown command.")
                    input("Press Enter to continue...")

if __name__ == "__main__":
    sim = Simulation()
    sim.run()