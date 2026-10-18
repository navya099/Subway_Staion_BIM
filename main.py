import tkinter as tk

from gui.gui_app import StationBIMApp


def main():
    root = tk.Tk()
    app = StationBIMApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()