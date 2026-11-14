import tkinter as tk






class SpaceApp:

    # Class variables - customise the appearance here
    font = "Arial"
    text_size = 16
    text_colour = "white"
    background_colour = "black"

    def __init__(self, font1, text_size1, text_colour1, bg_colour_1):
        self.font1 = font1
        self.text_size1 = text_size1
        self.text_colour1 = text_colour1
        self.bg_colour_1 = bg_colour_1

        self.home = home
        self.home.title("Space App")
        self.home.geometry("500x400")
        self.home.configure(bg=self.bg_colour_1)

        # Title
        self.title = tk.Label(
            self.home,
            text="space app",
            font=(self.font1, self.text_size1, "bold"),
            fg=self.text_colour1,
            bg=self.bg_colour_1
        )
        self.title.pack(pady=40)

        # Selection buttons
        self.button1 = self.create_button()
        self.button2 = self.create_button()
        self.button3 = self.create_button()

    # Function to create selection buttons
    def create_button(self):

        button = tk.Button(
            self.window,
            text="Select",
            font=(self.font1, self.text_size1),
            fg=self.text_colour1,
            bg=self.bg_colour_1,
            width=15
        )

        button.pack(pady=10)

        return button


# Run the application
window = tk.Tk()
app = SpaceApp("Arial", 15, "#ffffff", "#3D697F")
window.mainloop()