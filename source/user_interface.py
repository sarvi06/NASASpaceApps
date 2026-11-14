import tkinter as tk
from tkinter import ttk
from tkinter.messagebox import showinfo


class MainMenu(ttk.Frame):
    def __init__(self, container, background, font, size, colour1, colour2):
        self.background = background
        self.font = font
        self.size = size
        self.colour1 = colour1
        self.colour2 = colour2

        super().__init__(container)

        options = {'padx': 5, 'pady': 5}

        self.title = tk.Label(self, text="Space Apps",
                               font=(self.font, self.size,), bg=self.background, fg=colour1)
        self.title.pack(**options)

        self.button = tk.Button(self, text="Hello", command=self.button_clicked,
                                font=(self.font, self.size))
        self.button.pack(**options)

        self.pack(**options)

    def button_clicked(self):
        showinfo(title="Information",
                 message="Woh, crazy")


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Space App")
        self.geometry('600x800')
        self.configure(bg = '#313a69', cursor = 'heart')

if __name__ == "__main__":
    app = App()
    frame = MainMenu(app, "#313a69", font="Helvetica", size=12, colour1='#ffffff', colour2='#ffffff')
    app.mainloop()