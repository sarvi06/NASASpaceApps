import tkinter as tk
import tkinter.font as tkFont
import tkinter.ttk as ttk
from pathlib import Path



def mainmenu(background1, background2, active_background, cursor, font, size, colour1):


    window = tk.Tk()
    window.title("Satellite Support for Faming")
    window.configure(bg = background1, cursor = cursor)
    window.geometry("1300x800")

    plot_title_font = tkFont.Font(family=font, size=20, weight="bold")
    plot_font = tkFont.Font(family=font, size=size)
    
    plot_selection_frame = tk.Frame(window, bg=background2, width=400, height=780)
    plot_selection_frame.pack(padx=20, pady=20, anchor='w')

    title_label = tk.Label(plot_selection_frame, text="Plot Selection",
                           bg=background2, fg=colour1, font=plot_title_font)
    title_label.pack(pady=20, padx=10)

    plot_values = {'Plot 1' : '1',
                   'Plot 2' : '2',
                   'Plot 3' : '3',
                   'Plot 4' : '4',
                   'Plot 5' : '5'}

    plot_button_photo = tk.PhotoImage(file = "images/plot1icon.png")

    s = ttk.Style()
    s.configure('Plots.TRadiobutton',
            background=background2,
            indicator=0)   

    # Creating the list of radio buttons using a loop
    for (text, value) in plot_values.items():
        plot_button = ttk.Radiobutton(plot_selection_frame,
                       image=plot_button_photo, value=value,
                       style='Plots.TRadiobutton')
        plot_button.pack(ipady=5)

    
    window.mainloop()

mainmenu(background1="#E0EAF0", background2="#788ebd", active_background="#DEDDFF",
         cursor='star', font='Tw Cen MT', size=20,
         colour1="#0A1D2B")