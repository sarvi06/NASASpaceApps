import tkinter as tk
import tkinter.font as tkFont




def mainmenu(background, active_background, cursor, font, size, colour1):
    window = tk.Tk()
    window.title("NASA Space App")
    window.configure(bg = background, cursor = cursor)
    window.geometry("600x800")

    title_font = tkFont.Font(family=font, size=40)
    text_font = tkFont.Font(family=font, size=size)
    
    options_frame = tk.Frame(window, bg=background, width=400, height=700)
    options_frame.pack(padx=10, pady=10)

    title_label = tk.Label(options_frame, text="NASA Space App",
                           bg=background, fg=colour1, font=title_font)
    title_label.pack(pady=100, padx=10)

    support_button = tk.Button(options_frame, text="Support",
                               bg=background, fg=colour1, font=text_font,
                               activebackground=active_background, activeforeground=colour1)
    support_button.pack(padx=10, pady=10)


    
    window.mainloop()

mainmenu(background='#403761', active_background="#605586",
         cursor='star', font='Terminal', size=20,
         colour1='#ffffff')