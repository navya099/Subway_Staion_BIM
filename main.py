import tkinter as tk

from gui.gui import StationBIMApp


def main():
    root = tk.Tk()
    app = StationBIMApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()