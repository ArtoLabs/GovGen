# utils.py
def choose_from_list(options, prompt, display_func=lambda x: str(x)):
    """
    Present a list of options to the user and allow selection by number.

    Args:
        options (list): The list of options to choose from.
        prompt (str): The prompt message to display.
        display_func (callable): A function to format each option for display.

    Returns:
        The selected option, or None if no options are available or selection fails.
    """
    if not options:
        print("No options available.")
        return None
    print(prompt)
    for i, option in enumerate(options, 1):
        print(f"  {i}: {display_func(option)}")
    while True:
        try:
            choice = int(input("Enter number: "))
            if 1 <= choice <= len(options):
                return options[choice - 1]
            else:
                print("Invalid number.")
        except ValueError:
            print("Please enter a number.")