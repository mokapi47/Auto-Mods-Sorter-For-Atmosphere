#!/usr/bin/env python3
"""Normalise la structure des mods Switch (romfs / exefs) et traite les archives."""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import tarfile
import shutil
import subprocess
import tempfile
import zipfile
import ctypes
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path
from typing import Optional
import re

# Add DPI awareness to improve display quality without changing scale
ctypes.windll.shcore.SetProcessDpiAwareness(2)

DEFAULT_TITLEID = "0100000000010000"
EXPECTED_RELATIVE_PATH = Path("contents") / DEFAULT_TITLEID / "romfs"
EXPECTED_EXEFS_RELATIVE_PATH = Path("contents") / DEFAULT_TITLEID / "exefs"
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"}
EXTRACT_ROOT_NAME = "_normalized_archives"
EXEFS_FILE_PREFIXES = ("subsdk", "sdk", "main")
EXEFS_FILE_EXACT = {"main.npdm"}
IGNORED_DEBUG_EXTENSIONS = {".elf"}

# Global variable for selected titleID
selected_titleid: Optional[str] = None


def load_titleid_database(db_path: Path) -> dict[str, list[str]]:
    database = {}
    
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or " - " not in line:
                    continue
                
                # Parser le format: "0100000000010000 - Super Mario Odyssey™"
                parts = line.split(" - ", 1)
                if len(parts) == 2:
                    titleid = parts[0].strip()
                    game_name = parts[1].strip()
                    
                    # Nettoyer le nom du jeu
                    game_name = game_name.replace('™', '').replace('®', '').strip()
                    
                    # Stocker comme chaîne de caractères
                    if titleid not in database:
                        database[titleid] = []
                    if game_name not in database[titleid]:
                        database[titleid].append(game_name)
                    
    except Exception as exc:
        print_status(f"[ERROR] Erreur lecture fichier texte: {exc}")
    
    # Debug: check first few keys and their types
    first_keys = list(database.keys())[:3]
    print_status(f"[DEBUG DB] First {len(first_keys)} database keys and types:")
    for key in first_keys:
        print_status(f"[DEBUG DB] Key: '{key}', Type: {type(key)}")
    
    print_status(f"[INFO] Base de données chargée: {len(database)} jeux depuis {db_path.name}")
    return database


class GameSelectorGUI:
    """Interface graphique pour la selection de jeu avec barre de recherche."""
    
    def __init__(self, database: dict[str, list[str]], folder_name: str):
        self.database = database
        self.folder_name = folder_name
        self.selected_titleid: Optional[str] = None
        self.selected_game_name: Optional[str] = None
        self.root = tk.Tk()
        self.root.title(f"Sélection de jeu - {folder_name}")
        self.root.geometry("1000x780")
        self.root.resizable(True, True)
        
        # Configuration des couleurs
        self.colors = {
            'bg': '#2b2b2b',
            'fg': '#ffffff',
            'accent': '#4a90d9',
            'accent_hover': '#357abd',
            'header_bg': '#3c3c3c',
            'row_even': '#333333',
            'row_odd': '#2b2b2b',
            'selected': '#4a90d9'
        }
        
        # Configuration du style
        self.setup_style()
        self.setup_ui()
        
        # Handler pour la fermeture via le bouton X
        self.root.protocol("WM_DELETE_WINDOW", self.cancel_selection)
        
        # Animation d'ouverture (fade-in)
        self.root.attributes('-alpha', 0.0)
        self.fade_in()
    
    def fade_in(self):
        """Animation de fade-in à l'ouverture."""
        alpha = self.root.attributes('-alpha')
        if alpha < 1.0:
            alpha += 0.04
            self.root.attributes('-alpha', alpha)
            self.root.after(25, self.fade_in)
    
    def fade_out(self, callback):
        """Animation de fade-out à la fermeture."""
        alpha = self.root.attributes('-alpha')
        if alpha > 0.0:
            alpha -= 0.05
            self.root.attributes('-alpha', alpha)
            self.root.after(20, lambda: self.fade_out(callback))
        else:
            callback()
        
    def setup_style(self):
        """Configure le style ttk personnalisé."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configuration des couleurs de base
        style.configure('TFrame', background=self.colors['bg'])
        style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['fg'], font=('Segoe UI', 9))
        style.configure('TButton', font=('Segoe UI', 9, 'bold'), padding=8)
        style.configure('Header.TLabel', font=('Segoe UI', 12, 'bold'), foreground=self.colors['accent'])
        style.configure('Title.TLabel', font=('Segoe UI', 9))
        
        # Configuration des boutons
        style.configure('Confirm.TButton', font=('Segoe UI', 11, 'bold'))
        style.configure('Cancel.TButton', font=('Segoe UI', 11))
        
        # Configuration de la Treeview
        style.configure('Treeview', 
                       background=self.colors['row_even'],
                       foreground=self.colors['fg'],
                       fieldbackground=self.colors['row_even'],
                       font=('Consolas', 9),
                       rowheight=24,
                       borderwidth=0)
        style.configure('Treeview.Heading',
                       background=self.colors['header_bg'],
                       foreground=self.colors['fg'],
                       font=('Consolas', 9, 'bold'),
                       borderwidth=0)
        # Garder la sélection bleue mais désactiver le flash blanc sur hover
        style.map('Treeview',
                 background=[('selected', self.colors['selected'])],
                 foreground=[('selected', '#ffffff')])
        style.map('Treeview.Heading', background=[])
        style.map('Treeview.Heading', foreground=[])
        
        # Configuration de la Scrollbar personnalisée - noir
        style.configure('Vertical.TScrollbar',
                       background='#1a1a1a',
                       troughcolor='#2b2b2b',
                       bordercolor='#1a1a1a',
                       arrowcolor='#ffffff',
                       relief='flat',
                       arrowsize=10)
        
        # Configuration de l'Entry
        style.configure('TEntry', fieldbackground=self.colors['header_bg'], 
                       foreground=self.colors['fg'], font=('Segoe UI', 10))
        
        self.root.configure(bg=self.colors['bg'])
        
    def setup_ui(self):
        """Configure l'interface utilisateur."""
        # Frame principal
        main_frame = ttk.Frame(self.root, padding="0")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=15, pady=15)
        
        # Configuration du grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Frame pour les éléments du haut (titre, dossier, recherche)
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Titre
        title_label = ttk.Label(
            top_frame, 
            text=f"Sélectionnez le jeu pour le dossier:",
            style='Header.TLabel'
        )
        title_label.grid(row=0, column=0, pady=(0, 0), sticky=tk.W)
        
        folder_label = ttk.Label(
            top_frame, 
            text=self.folder_name,
            style='Title.TLabel',
            foreground='#888888'
        )
        folder_label.grid(row=1, column=0, pady=(0, 0), sticky=tk.W)
        
        # Barre de recherche
        search_frame = ttk.Frame(top_frame)
        search_frame.grid(row=2, column=0, pady=(0, 5), sticky=(tk.W, tk.E))
        search_frame.columnconfigure(1, weight=1)
        
        search_label = ttk.Label(search_frame, text="🔍 Rechercher:", font=('Segoe UI', 10))
        search_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self.filter_games)
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, font=('Segoe UI', 10))
        search_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 0))
        search_entry.focus()
        
        # Liste des jeux
        list_frame = ttk.Frame(main_frame)
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        columns = ("titleid", "game_name")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("titleid", text="TitleID", anchor='center')
        self.tree.heading("game_name", text="Nom du jeu", anchor='w')
        self.tree.column("titleid", width=200, anchor='center')
        self.tree.column("game_name", width=630, anchor='w')

        # Forcer toutes les colonnes à être traitées comme des strings
        for col in columns:
            self.tree.column(col, stretch=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview, style='Vertical.TScrollbar')
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Double-clic pour confirmer
        self.tree.bind("<Double-1>", lambda e: self.confirm_selection())
        
        # Configuration des couleurs alternées pour les lignes
        self.tree.tag_configure('odd', background=self.colors['row_odd'])
        self.tree.tag_configure('even', background=self.colors['row_even'])
        
        # Boutons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, pady=(0, 0), sticky=(tk.E, tk.W))
        
        confirm_button = tk.Button(
            button_frame, 
            text="✓ Confirmer", 
            command=self.confirm_selection,
            bg=self.colors['accent'],
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            padx=20,
            pady=6,
            relief='flat',
            cursor='hand2',
            activebackground=self.colors['accent_hover']
        )
        confirm_button.grid(row=0, column=0, padx=(0, 10))
        
        cancel_button = tk.Button(
            button_frame, 
            text="✗ Annuler", 
            command=self.cancel_selection,
            bg='#555555',
            fg='white',
            font=('Segoe UI', 9),
            padx=20,
            pady=6,
            relief='flat',
            cursor='hand2',
            activebackground='#666666'
        )
        cancel_button.grid(row=0, column=1, padx=(10, 0))
        
        # Charger les jeux
        self.load_games()
        
    def load_games(self):
        """Charge tous les jeux dans la liste sans tri."""
        self.tree.delete(*self.tree.get_children())
        
        # Insérer sans tri
        idx = 0
        for titleid, game_names in self.database.items():
            for game_name in game_names:
                tag = 'even' if idx % 2 == 0 else 'odd'
                # Forcer explicitement la conversion en string pour éviter la conversion auto en int par tkinter
                self.tree.insert("", tk.END, values=(str(titleid), game_name), tags=(tag,))
                idx += 1
    
    def filter_games(self, *args):
        """Filtre les jeux selon la recherche sans tri."""
        search_term = self.search_var.get().lower()
        self.tree.delete(*self.tree.get_children())
        
        # Insérer sans tri
        idx = 0
        for titleid, game_names in self.database.items():
            for game_name in game_names:
                if (search_term in str(titleid).lower() or 
                    search_term in game_name.lower()):
                    tag = 'even' if idx % 2 == 0 else 'odd'
                    # Forcer explicitement la conversion en string pour éviter la conversion auto en int par tkinter
                    self.tree.insert("", tk.END, values=(str(titleid), game_name), tags=(tag,))
                    idx += 1
    
    def confirm_selection(self):
        """Confirme la selection du jeu."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner un jeu.")
            return

        item = self.tree.item(selection[0])
        game_name = item["values"][1]
        self.selected_game_name = game_name

        # Récupérer le titleID depuis la base de données en utilisant le nom du jeu
        # pour éviter les problèmes de conversion depuis la Treeview
        for titleid, game_names in self.database.items():
            if game_name in game_names:
                self.selected_titleid = titleid
                break
        else:
            # Fallback : utiliser la valeur de la Treeview si non trouvé
            self.selected_titleid = str(item["values"][0])

        self.fade_out(self.root.destroy)
    
    def cancel_selection(self):
        """Annule la selection."""
        self.selected_titleid = None
        self.selected_game_name = None
        self.fade_out(self.root.destroy)
    
    def run(self) -> tuple[Optional[str], Optional[str]]:
        """Affiche la GUI et retourne la selection."""
        self.root.mainloop()
        return self.selected_titleid, self.selected_game_name


def select_game_for_folder(folder_name: str, database: dict[str, list[str]]) -> Optional[str]:
    """Affiche la GUI pour selectionner un jeu et retourne le titleID."""
    if not database:
        print_status(f"[ERROR] Base de donnees vide, impossible de selectionner un jeu.")
        return None
    
    gui = GameSelectorGUI(database, folder_name)
    titleid, game_name = gui.run()
    
    if titleid:
        titleid = str(titleid)  # Ensure titleid is always a string
        print_status(f"[DEBUG] TitleID type: {type(titleid)}, value: '{titleid}'")
        print_status(f"[OK] Jeu selectionne: {game_name} (TitleID: {titleid})")
        return titleid
    else:
        print_status("[INFO] Selection annulee ou aucun jeu selectionne.")
        return None


def is_extract_work_dir(name: str) -> bool:
    """Dossiers temporaires d'extraction (prefixe _normalized_archives...)."""
    return name == EXTRACT_ROOT_NAME or name.startswith(f"{EXTRACT_ROOT_NAME}_") or name.startswith("https___")

COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[32m"
COLOR_ORANGE = "\033[33m"
COLOR_RED = "\033[31m"


class DebugLogger:
    def __init__(self, enabled: bool, output_dir: Path):
        self.enabled = enabled
        self.path = output_dir / "debug.txt"
        if self.enabled:
            self.path.write_text(
                f"[{datetime.now().isoformat(sep=' ', timespec='seconds')}] "
                "Debut execution normalize_romfs_structure.py\n",
                encoding="utf-8",
            )

    def log(self, step: str, detail: str) -> None:
        if not self.enabled:
            return
        line = (
            f"[{datetime.now().isoformat(sep=' ', timespec='seconds')}] "
            f"[{step}] {detail}\n"
        )
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass


def configure_console_line_by_line() -> None:
    """Affiche chaque ligne tout de suite (evite le blocage du buffer stdout)."""
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        pass
    try:
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        pass


def enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    if handle == 0:
        return
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
        return
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def print_status(message: str) -> None:
    color = ""
    if message.startswith("[OK]"):
        color = COLOR_GREEN
    elif message.startswith("[WARN]"):
        color = COLOR_ORANGE
    elif message.startswith("[ERROR]") or message.startswith("WARN_ERROR:"):
        color = COLOR_RED

    if color:
        try:
            print(f"{color}{message}{COLOR_RESET}", flush=True)
        except UnicodeEncodeError:
            print(f"{color}{message.encode('ascii', 'replace').decode('ascii')}{COLOR_RESET}", flush=True)
    else:
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            print(message.encode('ascii', 'replace').decode('ascii'), flush=True)


def record_error(error_list: list[str], context: str, exc: Exception, debug: DebugLogger | None = None) -> None:
    detail = f"{context}: {type(exc).__name__}: {exc}"
    error_list.append(detail)
    if debug:
        debug.log("ERROR", detail)


def _path_depth_under(base: Path, path: Path) -> int:
    try:
        return len(path.relative_to(base).parts)
    except ValueError:
        return 999999


def find_existing_romfs(folder: Path, expected_romfs: Path, debug: DebugLogger | None = None) -> Path | None:
    """Find an existing romfs folder to move, excluding the expected destination."""
    if debug:
        debug.log("SCAN", f"Recherche romfs dans '{folder}' (cible attendue: '{expected_romfs}').")

    direct = folder / "romfs"
    if direct.exists() and direct.is_dir():
        if debug:
            debug.log("SCAN", f"Romfs trouve directement: '{direct}'.")
        return direct

    candidates: list[Path] = []
    for candidate in folder.rglob("romfs"):
        if candidate == expected_romfs:
            if debug:
                debug.log("SCAN", f"Romfs ignore (deja cible attendue): '{candidate}'.")
            continue
        if not candidate.is_dir():
            if debug:
                debug.log("SCAN", f"Chemin ignore car pas dossier: '{candidate}'.")
            continue
        candidates.append(candidate)

    if not candidates:
        if debug:
            debug.log("SCAN", f"Aucun romfs trouve dans '{folder}'.")
        return None

    candidates.sort(key=lambda p: (_path_depth_under(folder, p), str(p).lower()))
    chosen = candidates[0]
    if debug:
        debug.log("SCAN", f"Romfs candidat retenu (plus proche de la racine): '{chosen}'.")
    return chosen


def _is_safe_member_path(member_name: str, dest: Path) -> bool:
    dest = dest.resolve()
    member_path = Path(member_name)
    if member_path.is_absolute():
        return False
    if ".." in member_path.parts:
        return False
    target = (dest / member_name).resolve()
    try:
        target.relative_to(dest)
    except ValueError:
        return False
    return True


def safe_extract_zip(archive_path: Path, output_dir: Path, debug: DebugLogger | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            if not _is_safe_member_path(info.filename, output_dir):
                if debug:
                    debug.log("ARCHIVE", f"Entree zip ignoree (chemin non sur): '{info.filename}'.")
                continue
            zf.extract(info, path=output_dir)


def safe_extract_tar(archive_path: Path, output_dir: Path, debug: DebugLogger | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            try:
                is_sym = member.issym()
            except AttributeError:
                is_sym = False
            if is_sym:
                if debug:
                    debug.log("ARCHIVE", f"Lien symbolique tar ignore: '{member.name}'.")
                continue
            if not _is_safe_member_path(member.name, output_dir):
                if debug:
                    debug.log("ARCHIVE", f"Entree tar ignoree (chemin non sur): '{member.name}'.")
                continue
            try:
                tf.extract(member, path=output_dir, filter="data")  # type: ignore[call-arg]
            except TypeError:
                tf.extract(member, path=output_dir)


def is_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    suffixes = {s.lower() for s in path.suffixes}
    return bool(suffixes & ARCHIVE_EXTENSIONS)


def resolve_output_dir(archive_path: Path, extract_root: Path) -> Path:
    safe_name = archive_path.name.replace(".", "_")
    return extract_root / safe_name


def resolve_unique_destination(base_dir: Path, preferred_name: str) -> Path:
    candidate = base_dir / preferred_name
    if not candidate.exists():
        return candidate

    index = 1
    while True:
        alt = base_dir / f"{preferred_name}_{index}"
        if not alt.exists():
            return alt
        index += 1


def sanitize_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in name).strip()
    return cleaned or "mod_result"


def unwrap_atmosphere_folder(
    target_folder: Path,
    output_dir: Path,
    archive_name: str,
    debug: DebugLogger | None = None,
) -> tuple[Path, str]:
    if target_folder.name.lower() != "atmosphere":
        return target_folder, ""

    preferred = sanitize_name(Path(archive_name).stem)
    new_root = resolve_unique_destination(output_dir, preferred)
    new_root.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    for child in list(target_folder.iterdir()):
        destination = new_root / child.name
        if destination.exists():
            if debug:
                debug.log(
                    "SELECT",
                    f"Collision atmosphere: '{destination}' existe deja, element ignore '{child}'.",
                )
            continue
        shutil.move(str(child), str(destination))
        moved_count += 1

    try:
        shutil.rmtree(target_folder, ignore_errors=True)
    except OSError:
        pass

    if debug:
        debug.log(
            "SELECT",
            f"Wrapper 'atmosphere' retire pour '{archive_name}', {moved_count} element(s) deplaces vers '{new_root}'.",
        )
    return new_root, (
        f"[INFO] {archive_name}: dossier 'atmosphere' ignore, contenu interne utilise via '{new_root}'."
    )


def extract_archive(
    archive_path: Path,
    output_dir: Path,
    dry_run: bool = False,
    debug: DebugLogger | None = None,
) -> tuple[bool, str]:
    if debug:
        debug.log("ARCHIVE", f"Debut extraction '{archive_path}' vers '{output_dir}' (dry_run={dry_run}).")

    if dry_run:
        if debug:
            debug.log("ARCHIVE", f"Dry-run extraction terminee pour '{archive_path.name}'.")
        return True, f"[DRY-RUN] Extraction de '{archive_path.name}' vers '{output_dir}'."

    output_dir.mkdir(parents=True, exist_ok=True)
    if debug:
        debug.log("ARCHIVE", f"Dossier d'extraction cree/verifie: '{output_dir}'.")

    try:
        # Extraction Python native pour zip/tar et derives.
        suffixes = [s.lower() for s in archive_path.suffixes]
        suffix = suffixes[-1] if suffixes else ""

        if suffix == ".zip":
            safe_extract_zip(archive_path, output_dir, debug)
        elif suffix in {".tar", ".gz", ".bz2", ".xz"} or (
            len(suffixes) >= 2 and "".join(suffixes[-2:]) in {".tar.gz", ".tar.bz2", ".tar.xz"}
        ):
            safe_extract_tar(archive_path, output_dir, debug)
        else:
            raise ValueError("format non gere nativement")

        if debug:
            debug.log("ARCHIVE", f"Extraction Python native reussie pour '{archive_path.name}'.")
        return True, f"[OK] Archive extraite: {archive_path.name}"
    except Exception as exc:
        if debug:
            debug.log(
                "ARCHIVE",
                f"Extraction Python native non disponible/echouee pour '{archive_path.name}': {exc}",
            )

    # Extraction Python via bibliotheques optionnelles.
    suffix = archive_path.suffix.lower()
    if suffix == ".7z":
        try:
            py7zr = importlib.import_module("py7zr")
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=output_dir)
            if debug:
                debug.log("ARCHIVE", f"Extraction py7zr reussie pour '{archive_path.name}'.")
            return True, f"[OK] Archive extraite avec py7zr: {archive_path.name}"
        except ModuleNotFoundError:
            if debug:
                debug.log(
                    "ARCHIVE",
                    "Module py7zr absent. Installe-le avec: pip install py7zr",
                )
        except Exception as exc:
            if debug:
                debug.log("ARCHIVE", f"Echec py7zr pour '{archive_path.name}': {exc}")

    if suffix == ".rar":
        try:
            rarfile = importlib.import_module("rarfile")
            with rarfile.RarFile(archive_path) as archive:
                archive.extractall(path=output_dir)
            if debug:
                debug.log("ARCHIVE", f"Extraction rarfile reussie pour '{archive_path.name}'.")
            return True, f"[OK] Archive extraite avec rarfile: {archive_path.name}"
        except ModuleNotFoundError:
            if debug:
                debug.log(
                    "ARCHIVE",
                    "Module rarfile absent. Installe-le avec: pip install rarfile",
                )
        except Exception as exc:
            if debug:
                debug.log("ARCHIVE", f"Echec rarfile pour '{archive_path.name}': {exc}")

    # Fallback final via 7z executable (si present)
    candidate_paths: list[str] = []
    candidate_paths.extend(
        p for p in (shutil.which("7z"), shutil.which("7za")) if p
    )
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidate_paths.extend(
        [
            str(Path(program_files) / "7-Zip" / "7z.exe"),
            str(Path(program_files_x86) / "7-Zip" / "7z.exe"),
        ]
    )
    seven_zip = next((p for p in candidate_paths if Path(p).exists()), None)
    if seven_zip is None:
        if debug:
            debug.log(
                "ARCHIVE",
                "Echec extraction: aucun backend disponible (native/py7zr/rarfile/7z).",
            )
        return False, (
            f"[ERROR] Impossible d'extraire '{archive_path.name}' "
            "(backend manquant). Installe pip packages 'py7zr' et 'rarfile', "
            "ou verifie 7-Zip."
        )

    try:
        completed = subprocess.run(
            [seven_zip, "x", str(archive_path), f"-o{output_dir}", "-y"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        if debug:
            debug.log("ARCHIVE", f"Echec subprocess 7z pour '{archive_path.name}': {exc}")
        return False, f"[ERROR] Echec extraction '{archive_path.name}': {exc}"

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout).strip() or "erreur inconnue"
        if debug:
            debug.log("ARCHIVE", f"Echec 7z pour '{archive_path.name}': {err}")
        return False, f"[ERROR] Echec extraction '{archive_path.name}': {err}"
    if debug:
        debug.log("ARCHIVE", f"Extraction 7z reussie pour '{archive_path.name}'.")
    return True, f"[OK] Archive extraite avec 7z: {archive_path.name}"


def repair_nested_exefs_folder(expected_exefs: Path, debug: DebugLogger | None = None) -> None:
    """Si une ancienne version a cree contents/.../exefs/exefs, aplatit en un seul exefs."""
    nested = expected_exefs / "exefs"
    if not nested.is_dir():
        return
    if debug:
        debug.log(
            "NORMALIZE",
            f"Reparation exefs imbrique: fusion de '{nested}' vers '{expected_exefs}'.",
        )
    for child in list(nested.iterdir()):
        destination = expected_exefs / child.name
        if destination.exists():
            if debug:
                debug.log(
                    "NORMALIZE",
                    f"Reparation: collision sur '{destination}', ignore '{child}'.",
                )
            continue
        shutil.move(str(child), str(destination))
    try:
        nested.rmdir()
    except OSError:
        pass


def choose_second_folder(base: Path, debug: DebugLogger | None = None, titleid: Optional[str] = None) -> tuple[Path | None, str]:
    if debug:
        debug.log("SELECT", f"Selection du dossier cible dans '{base}'.")

    use_titleid = str(titleid) if titleid else str(DEFAULT_TITLEID)

    # Priorite forte: trouver un vrai romfs et remonter au bon dossier racine du mod.
    romfs_dirs = [p for p in base.rglob("romfs") if p.is_dir()]
    romfs_dirs.sort(key=lambda p: (_path_depth_under(base, p), str(p).lower()))
    for romfs_dir in romfs_dirs:
        try:
            rel_parts = [part.lower() for part in romfs_dir.relative_to(base).parts]
        except ValueError:
            continue

        # Si le chemin contient contents/titleid/romfs, remonter au dossier avant contents
        # Vérifier si c'est un titleID (16 caractères hexadécimaux) après 'contents'
        if "contents" in rel_parts:
            contents_idx = rel_parts.index("contents")
            if contents_idx + 2 < len(rel_parts):
                potential_titleid = rel_parts[contents_idx + 1]
                if rel_parts[contents_idx + 2] == "romfs" and len(potential_titleid) == 16 and all(c in "0123456789abcdef" for c in potential_titleid):
                    # Structure: .../contents/titleid/romfs -> racine = dossier avant contents
                    root_candidate = romfs_dir
                    for _ in range(3):  # remonter de 3 niveaux: romfs -> titleid -> contents -> racine
                        root_candidate = root_candidate.parent
                    # Vérifier si le résultat est encore un titleID, si oui remonter encore
                    if len(root_candidate.name) == 16 and all(c in "0123456789ABCDEFabcdef" for c in root_candidate.name):
                        root_candidate = root_candidate.parent
                    if debug:
                        debug.log(
                            "SELECT",
                            f"Romfs avec structure contents/titleid/romfs detecte '{romfs_dir}', racine mod='{root_candidate}'.",
                        )
                    return root_candidate, f"racine mod detectee via structure contents: '{root_candidate}'"

        # Structure standard: mod_name/romfs
        root_candidate = romfs_dir.parent
        if debug:
            debug.log(
                "SELECT",
                f"Romfs detecte '{romfs_dir}', racine mod deduite='{root_candidate}'.",
            )
        return root_candidate, f"racine mod detectee via romfs: '{root_candidate}'."

    # Priorite exefs: meme logique que romfs pour les mods exefs-only.
    exefs_dirs = [p for p in base.rglob("exefs") if p.is_dir()]
    exefs_dirs.sort(key=lambda p: (_path_depth_under(base, p), str(p).lower()))
    for exefs_dir in exefs_dirs:
        try:
            rel_parts = [part.lower() for part in exefs_dir.relative_to(base).parts]
        except ValueError:
            continue

        # Si le chemin contient contents/titleid/exefs, remonter au dossier avant contents
        # Vérifier si c'est un titleID (16 caractères hexadécimaux) après 'contents'
        if "contents" in rel_parts:
            contents_idx = rel_parts.index("contents")
            if contents_idx + 2 < len(rel_parts):
                potential_titleid = rel_parts[contents_idx + 1]
                if rel_parts[contents_idx + 2] == "exefs" and len(potential_titleid) == 16 and all(c in "0123456789abcdef" for c in potential_titleid):
                    # Structure: .../contents/titleid/exefs -> racine = dossier avant contents
                    root_candidate = exefs_dir
                    for _ in range(3):  # remonter de 3 niveaux: exefs -> titleid -> contents -> racine
                        root_candidate = root_candidate.parent
                    # Vérifier si le résultat est encore un titleID, si oui remonter encore
                    if len(root_candidate.name) == 16 and all(c in "0123456789ABCDEFabcdef" for c in root_candidate.name):
                        root_candidate = root_candidate.parent
                    if debug:
                        debug.log(
                            "SELECT",
                            f"Exefs avec structure contents/titleid/exefs detecte '{exefs_dir}', racine mod='{root_candidate}'.",
                        )
                    return root_candidate, f"racine mod detectee via structure contents (exefs): '{root_candidate}'"

        # Structure standard: mod_name/exefs
        root_candidate = exefs_dir.parent
        if debug:
            debug.log(
                "SELECT",
                f"Exefs detecte '{exefs_dir}', racine mod deduite='{root_candidate}'.",
            )
        return root_candidate, f"racine mod detectee via exefs: '{root_candidate}'."

    first_level_dirs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
    if not first_level_dirs:
        if debug:
            debug.log("SELECT", f"Aucun dossier premier niveau dans '{base}'.")
        return None, "aucun dossier trouve a la racine de l'archive extraite."

    second_level_dirs: list[tuple[Path, Path]] = []
    for first in first_level_dirs:
        for second in sorted([p for p in first.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            second_level_dirs.append((first, second))

    # Cas attendu: wrapper/mod_name/... ; on prefere le 2e dossier s'il n'est pas romfs/exefs seuls.
    second_level_non_special = [
        second
        for _, second in second_level_dirs
        if second.name.lower() not in {"romfs", "exefs"}
    ]
    if second_level_non_special:
        chosen = second_level_non_special[0]
        if debug:
            debug.log("SELECT", f"2e niveau (hors romfs/exefs) retenu: '{chosen}'.")
        return chosen, f"dossier cible interne detecte: '{chosen}'."

    if second_level_dirs:
        # Cas frequent: wrapper/romfs ou wrapper/exefs ; la racine du mod est le parent.
        first, second = second_level_dirs[0]
        if second.name.lower() == "romfs":
            if debug:
                debug.log("SELECT", f"2e niveau = romfs ('{second}'), parent retenu: '{first}'.")
            return first, (
                "deuxieme dossier = 'romfs', utilisation du dossier parent "
                f"du mod: '{first}'."
            )
        if second.name.lower() == "exefs":
            if debug:
                debug.log("SELECT", f"2e niveau = exefs ('{second}'), parent retenu: '{first}'.")
            return first, (
                "deuxieme dossier = 'exefs', utilisation du dossier parent "
                f"du mod: '{first}'."
            )

    # Fallback robuste: certaines archives n'ont qu'un seul niveau.
    chosen = first_level_dirs[0]
    if debug:
        debug.log("SELECT", f"Fallback premier niveau retenu: '{chosen}'.")
    return chosen, (
        "pas de deuxieme dossier detecte, utilisation du premier dossier "
        f"'{chosen}'."
    )


def normalize_folder(folder: Path, dry_run: bool = False, debug: DebugLogger | None = None, titleid: Optional[str] = None) -> str:
    original_folder = folder
    if folder.name.lower() == "romfs":
        if debug:
            debug.log("NORMALIZE", f"Dossier cible etait romfs ('{folder}'), bascule vers parent.")
        folder = folder.parent
    elif folder.name.lower() == "exefs":
        if debug:
            debug.log("NORMALIZE", f"Dossier cible etait exefs ('{folder}'), bascule vers parent.")
        folder = folder.parent

    use_titleid = str(titleid) if titleid else str(DEFAULT_TITLEID)

    # Détecter s'il y a déjà un titleID dans contents (structure: contents/TITLEID/romfs ou exefs)
    # Si oui, utiliser ce titleID au lieu de celui sélectionné
    contents_dir = folder / "contents"
    if contents_dir.exists() and contents_dir.is_dir():
        for child in contents_dir.iterdir():
            if child.is_dir() and len(child.name) == 16 and all(c in "0123456789ABCDEFabcdef" for c in child.name):
                # C'est un titleID, l'utiliser à la place
                use_titleid = child.name
                if debug:
                    debug.log("NORMALIZE", f"TitleID détecté dans l'archive: '{use_titleid}', utilisation à la place du titleID sélectionné")
                break
    
    # Détecter si le dossier lui-même est un titleID (structure: mod/titleID/romfs)
    # Si oui, remonter au parent pour fusionner
    if folder.name == use_titleid and folder.parent != original_folder.parent:
        if debug:
            debug.log("NORMALIZE", f"Le dossier est un titleID '{folder.name}', remontée au parent '{folder.parent}'")
        folder = folder.parent
    
    # Détecter si le dossier contient un dossier titleID (structure: mod/titleID/romfs)
    # Si oui, fusionner le contenu du titleID dans le parent
    titleid_subfolder = folder / use_titleid
    if titleid_subfolder.exists() and titleid_subfolder.is_dir():
        if debug:
            debug.log("NORMALIZE", f"Detection sous-dossier titleID '{titleid_subfolder}' dans '{folder}'")
        # Fusionner le contenu du sous-dossier titleID dans le parent
        for item in list(titleid_subfolder.iterdir()):
            destination = folder / item.name
            if destination.exists():
                if debug:
                    debug.log("NORMALIZE", f"Collision: '{destination}' existe deja, ignore '{item}'")
                continue
            try:
                shutil.move(str(item), str(destination))
                if debug:
                    debug.log("NORMALIZE", f"Fusion: '{item}' -> '{destination}'")
            except OSError as exc:
                if debug:
                    debug.log("NORMALIZE", f"Echec fusion '{item}' -> '{destination}': {exc}")
        # Supprimer le dossier titleID vide
        try:
            titleid_subfolder.rmdir()
            if debug:
                debug.log("NORMALIZE", f"Dossier titleID vide supprimé: '{titleid_subfolder}'")
        except OSError:
            if debug:
                debug.log("NORMALIZE", f"Impossible de supprimer le dossier titleID: '{titleid_subfolder}'")
    
    expected_romfs = folder / "contents" / use_titleid / "romfs"
    expected_exefs = folder / "contents" / use_titleid / "exefs"
    if debug:
        debug.log(
            "NORMALIZE",
            f"Normalisation dossier='{folder}' (entree='{original_folder}') cible='{expected_romfs}'.",
        )

    if expected_romfs.exists() and expected_romfs.is_dir():
        if debug:
            debug.log("NORMALIZE", f"Structure deja correcte pour '{folder}'.")
        return f"[OK] {folder.name}: structure deja correcte."
    if expected_exefs.exists() and expected_exefs.is_dir() and any(expected_exefs.iterdir()):
        repair_nested_exefs_folder(expected_exefs, debug=debug)
        if debug:
            debug.log("NORMALIZE", f"Structure exefs deja correcte pour '{folder}'.")
        return f"[OK] {folder.name}: structure deja correcte (exefs)."

    # Gestion mods exefs (ex: main.npdm, subsdk9...) comme l'exemple SMO_Online.
    direct_exefs = folder / "exefs"
    loose_exefs_files: list[Path] = []

    for item in folder.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() in IGNORED_DEBUG_EXTENSIONS:
            if debug:
                debug.log("NORMALIZE", f"Fichier debug ignore: '{item}'.")
            continue
        lowered = item.name.lower()
        if lowered in EXEFS_FILE_EXACT or lowered.startswith(EXEFS_FILE_PREFIXES):
            loose_exefs_files.append(item)
            if debug:
                debug.log("NORMALIZE", f"Fichier exefs detecte: '{item}'.")

    has_exefs_work = (
        (direct_exefs.exists() and direct_exefs.is_dir() and any(direct_exefs.iterdir()))
        or loose_exefs_files
    )

    if has_exefs_work:
        if dry_run:
            if debug:
                debug.log(
                    "NORMALIZE",
                    f"Dry-run placement exefs vers '{expected_exefs}' (dossier direct + fichiers).",
                )
            return f"[DRY-RUN] {folder.name}: placer contenu exefs vers '{expected_exefs}'."

        expected_exefs.mkdir(parents=True, exist_ok=True)
        if debug:
            debug.log("NORMALIZE", f"Dossier exefs cible cree/verifie: '{expected_exefs}'.")

        # Dossier exefs a la racine du mod: fusionner le CONTENU dans contents/.../exefs
        # (ne pas deplacer le dossier "exefs" lui-meme, sinon on obtient exefs/exefs).
        if direct_exefs.exists() and direct_exefs.is_dir():
            if debug:
                debug.log(
                    "NORMALIZE",
                    f"Dossier exefs direct detecte, fusion du contenu vers '{expected_exefs}': '{direct_exefs}'.",
                )
            for child in list(direct_exefs.iterdir()):
                destination = expected_exefs / child.name
                if destination.exists():
                    if debug:
                        debug.log(
                            "NORMALIZE",
                            f"Collision exefs: '{destination}' existe deja, element ignore '{child}'.",
                        )
                    continue
                shutil.move(str(child), str(destination))
                if debug:
                    debug.log("NORMALIZE", f"Deplacement exefs: '{child}' -> '{destination}'.")
            try:
                direct_exefs.rmdir()
            except OSError:
                if debug:
                    debug.log(
                        "NORMALIZE",
                        f"Dossier exefs racine non vide ou non supprimable: '{direct_exefs}'.",
                    )

        for source in loose_exefs_files:
            destination = expected_exefs / source.name
            if destination.exists():
                if debug:
                    debug.log(
                        "NORMALIZE",
                        f"Collision exefs: '{destination}' existe deja, element ignore '{source}'.",
                    )
                continue
            shutil.move(str(source), str(destination))
            if debug:
                debug.log("NORMALIZE", f"Deplacement exefs: '{source}' -> '{destination}'.")

        repair_nested_exefs_folder(expected_exefs, debug=debug)
        return f"[FIXED] {folder.name}: contenu exefs place vers '{expected_exefs}'."

    source_romfs = find_existing_romfs(folder, expected_romfs, debug=debug)
    if source_romfs is None:
        if debug:
            debug.log("NORMALIZE", f"Echec: aucun romfs source trouve pour '{folder}'.")
        return f"[SKIP] {folder.name}: aucun dossier 'romfs' trouve."

    if expected_romfs.exists():
        return f"[SKIP] {folder.name}: cible '{expected_romfs}' deja existante."

    target_parent = expected_romfs.parent
    if dry_run:
        if debug:
            debug.log("NORMALIZE", f"Dry-run deplacement '{source_romfs}' -> '{expected_romfs}'.")
        return f"[DRY-RUN] {folder.name}: deplacer '{source_romfs}' vers '{expected_romfs}'."

    target_parent.mkdir(parents=True, exist_ok=True)
    if debug:
        debug.log("NORMALIZE", f"Dossier parent cible cree/verifie: '{target_parent}'.")
    shutil.move(str(source_romfs), str(expected_romfs))
    if debug:
        debug.log("NORMALIZE", f"Deplacement effectif: '{source_romfs}' -> '{expected_romfs}'.")
    return f"[FIXED] {folder.name}: romfs deplace vers '{expected_romfs}'."


def detect_structure_type(folder: Path, debug: DebugLogger | None = None, titleid: Optional[str] = None) -> str:
    use_titleid = str(titleid) if titleid else str(DEFAULT_TITLEID)
    expected_romfs = folder / "contents" / use_titleid / "romfs"
    expected_exefs = folder / "contents" / use_titleid / "exefs"
    if expected_exefs.exists() and expected_exefs.is_dir():
        repair_nested_exefs_folder(expected_exefs, debug=debug)
    if expected_romfs.exists() and expected_romfs.is_dir():
        return "romfs"
    if expected_exefs.exists() and expected_exefs.is_dir() and any(expected_exefs.iterdir()):
        return "exefs"
    return "none"


def has_valid_structure(folder: Path, debug: DebugLogger | None = None, titleid: Optional[str] = None) -> bool:
    return detect_structure_type(folder, debug=debug, titleid=titleid) != "none"


def process_archives(
    root: Path,
    dry_run: bool = False,
    debug: DebugLogger | None = None,
    errors: list[str] | None = None,
    titleid: Optional[str] = None,
) -> list[str]:
    logs: list[str] = []
    errors = errors if errors is not None else []

    def emit_line(message: str) -> None:
        logs.append(message)
        print_status(message)

    archives = sorted([p for p in root.iterdir() if is_archive(p)], key=lambda p: p.name.lower())
    if debug:
        debug.log("ARCHIVE", f"Archives detectees: {[p.name for p in archives]}")
    if not archives:
        return logs

    emit_line("\n--- Traitement des archives ---")

    if dry_run:
        for archive in archives:
            try:
                temp_preview = root / EXTRACT_ROOT_NAME / archive.name.replace(".", "_")
                ok, message = extract_archive(archive, temp_preview, dry_run=True, debug=debug)
                emit_line(message)
                if not ok:
                    continue
                emit_line(
                    f"[DRY-RUN] {archive.name}: le resultat final sera deplace a cote de l'archive."
                )
            except Exception as exc:
                record_error(errors, f"Erreur dry-run archive '{archive.name}'", exc, debug)
                emit_line(f"[ERROR] {archive.name}: erreur inattendue, suite du traitement...")
        return logs

    with tempfile.TemporaryDirectory(prefix=f"{EXTRACT_ROOT_NAME}_", dir=str(root)) as temp_dir:
        extract_root = Path(temp_dir)
        if debug:
            debug.log("ARCHIVE", f"Dossier temporaire cree: '{extract_root}'.")

        for archive in archives:
            try:
                output_dir = resolve_output_dir(archive, extract_root)
                ok, message = extract_archive(archive, output_dir, dry_run=False, debug=debug)
                emit_line(message)
                if not ok:
                    continue

                # Détecter s'il y a plusieurs mods au premier niveau
                first_level_dirs = sorted([p for p in output_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
                
                if len(first_level_dirs) > 1:
                    # Traiter chaque mod séparément en normalisant directement le dossier mod
                    emit_line(f"[INFO] {archive.name}: {len(first_level_dirs)} mods détectés, traitement séparé.")
                    for mod_folder in first_level_dirs:
                        emit_line(normalize_folder(mod_folder, dry_run=False, debug=debug, titleid=titleid))
                        structure_type_before_move = detect_structure_type(mod_folder, debug=debug, titleid=titleid)
                        if structure_type_before_move == "none":
                            if debug:
                                debug.log(
                                    "VERIFY",
                                    f"Verification 1 echouee pour '{archive.name} - {mod_folder.name}' dans '{mod_folder}'.",
                                )
                            emit_line(
                                f"[ERROR] {archive.name} - {mod_folder.name}: verification apres normalisation echouee (ni romfs ni exefs valides) dans '{mod_folder}'."
                            )
                            continue
                        if debug:
                            debug.log(
                                "VERIFY",
                                f"Verification 1 OK pour '{archive.name} - {mod_folder.name}' dans '{mod_folder}' (type={structure_type_before_move}).",
                            )

                        destination = resolve_unique_destination(root, mod_folder.name)
                        try:
                            shutil.move(str(mod_folder), str(destination))
                        except OSError as exc:
                            if debug:
                                debug.log(
                                    "MOVE",
                                    f"Echec deplacement '{mod_folder}' -> '{destination}': {exc}",
                                )
                            emit_line(
                                f"[ERROR] {archive.name} - {mod_folder.name}: impossible de deplacer le resultat vers '{destination}': {exc}"
                            )
                            continue
                        if debug:
                            debug.log(
                                "MOVE",
                                f"Deplacement final reussi '{mod_folder}' -> '{destination}'.",
                            )
                        structure_type_after_move = detect_structure_type(destination, debug=debug, titleid=titleid)
                        if structure_type_after_move == "none":
                            if debug:
                                debug.log(
                                    "VERIFY",
                                    f"Verification 2 echouee pour '{archive.name} - {mod_folder.name}' dans '{destination}'.",
                                )
                            emit_line(
                                f"[ERROR] {archive.name} - {mod_folder.name}: verification apres deplacement echouee (ni romfs ni exefs valides) dans '{destination}'."
                            )
                            continue
                        if debug:
                            debug.log(
                                "VERIFY",
                                f"Verification 2 OK pour '{archive.name} - {mod_folder.name}' dans '{destination}' (type={structure_type_after_move}).",
                            )

                        emit_line(
                            f"[OK] {archive.name} - {mod_folder.name}: resultat deplace vers '{destination}' (structure {structure_type_after_move})."
                        )
                    
                    # Supprimer l'archive après traitement de tous les mods
                    try:
                        archive.unlink()
                    except OSError as exc:
                        if debug:
                            debug.log("CLEANUP", f"Suppression archive impossible '{archive}': {exc}")
                        emit_line(
                            f"[ERROR] {archive.name}: suppression archive impossible: {exc}"
                        )
                    else:
                        if debug:
                            debug.log("CLEANUP", f"Archive source supprimee: '{archive}'.")
                        emit_line(f"[OK] {archive.name}: archive source supprimee.")
                else:
                    # Traitement normal pour un seul mod
                    target_folder, reason = choose_second_folder(output_dir, debug=debug, titleid=titleid)
                    emit_line(f"[INFO] {archive.name}: {reason}")
                    if target_folder is None:
                        emit_line(f"[SKIP] {archive.name}: impossible de choisir un dossier interne.")
                        continue
                    target_folder, atmosphere_log = unwrap_atmosphere_folder(
                        target_folder=target_folder,
                        output_dir=output_dir,
                        archive_name=archive.name,
                        debug=debug,
                    )
                    if atmosphere_log:
                        emit_line(atmosphere_log)

                    emit_line(normalize_folder(target_folder, dry_run=False, debug=debug, titleid=titleid))
                    structure_type_before_move = detect_structure_type(target_folder, debug=debug, titleid=titleid)
                    if structure_type_before_move == "none":
                        if debug:
                            debug.log(
                                "VERIFY",
                                f"Verification 1 echouee pour '{archive.name}' dans '{target_folder}'.",
                            )
                        emit_line(
                            f"[ERROR] {archive.name}: verification apres normalisation echouee (ni romfs ni exefs valides) dans '{target_folder}'."
                        )
                        # Fallback robuste: on deplace au moins l'extraction brute, meme sans romfs.
                        raw_destination = resolve_unique_destination(root, target_folder.name)
                        try:
                            shutil.move(str(target_folder), str(raw_destination))
                            emit_line(
                                f"[INFO] {archive.name}: structure mod invalide (romfs/exefs), contenu extrait deplace brut vers '{raw_destination}'."
                            )
                            if debug:
                                debug.log(
                                    "FALLBACK",
                                    f"Deplacement brut applique pour '{archive.name}' vers '{raw_destination}'.",
                                )
                            try:
                                archive.unlink()
                            except OSError as unlink_exc:
                                emit_line(
                                    f"[ERROR] {archive.name}: deplacement brut OK mais suppression archive impossible: {unlink_exc}"
                                )
                            else:
                                emit_line(f"[OK] {archive.name}: archive source supprimee.")
                                if debug:
                                    debug.log("CLEANUP", f"Archive source supprimee apres fallback: '{archive}'.")
                        except OSError as move_exc:
                            emit_line(
                                f"[ERROR] {archive.name}: echec fallback deplacement brut vers '{raw_destination}': {move_exc}"
                            )
                            if debug:
                                debug.log(
                                    "FALLBACK",
                                    f"Echec deplacement brut pour '{archive.name}': {move_exc}",
                                )
                        continue
                    if debug:
                        debug.log(
                            "VERIFY",
                            f"Verification 1 OK pour '{archive.name}' dans '{target_folder}' (type={structure_type_before_move}).",
                        )

                    destination = resolve_unique_destination(root, target_folder.name)
                    try:
                        shutil.move(str(target_folder), str(destination))
                    except OSError as exc:
                        if debug:
                            debug.log(
                                "MOVE",
                                f"Echec deplacement '{target_folder}' -> '{destination}': {exc}",
                            )
                        emit_line(
                            f"[ERROR] {archive.name}: impossible de deplacer le resultat vers '{destination}': {exc}"
                        )
                        continue
                    if debug:
                        debug.log(
                            "MOVE",
                            f"Deplacement final reussi '{target_folder}' -> '{destination}'.",
                        )
                    structure_type_after_move = detect_structure_type(destination, debug=debug, titleid=titleid)
                    if structure_type_after_move == "none":
                        if debug:
                            debug.log(
                                "VERIFY",
                                f"Verification 2 echouee pour '{archive.name}' dans '{destination}'.",
                            )
                        emit_line(
                            f"[ERROR] {archive.name}: verification apres deplacement echouee (ni romfs ni exefs valides) dans '{destination}'."
                        )
                        continue
                    if debug:
                        debug.log(
                            "VERIFY",
                            f"Verification 2 OK pour '{archive.name}' dans '{destination}' (type={structure_type_after_move}).",
                        )

                    emit_line(
                        f"[OK] {archive.name}: resultat deplace vers '{destination}' (structure {structure_type_after_move})."
                    )
                    try:
                        archive.unlink()
                    except OSError as exc:
                        if debug:
                            debug.log("CLEANUP", f"Suppression archive impossible '{archive}': {exc}")
                        emit_line(
                            f"[ERROR] {archive.name}: structure valide mais suppression archive impossible: {exc}"
                        )
                    else:
                        if debug:
                            debug.log("CLEANUP", f"Archive source supprimee: '{archive}'.")
                        emit_line(f"[OK] {archive.name}: archive source supprimee.")
            except Exception as exc:
                record_error(errors, f"Erreur inattendue archive '{archive.name}'", exc, debug)
                emit_line(f"[ERROR] {archive.name}: erreur inattendue, suite du traitement...")

    # Nettoie un ancien dossier persistant d'une version precedente du script.
    legacy_extract_root = root / EXTRACT_ROOT_NAME
    if legacy_extract_root.exists():
        try:
            shutil.rmtree(legacy_extract_root)
            if debug:
                debug.log("CLEANUP", f"Ancien dossier temporaire supprime: '{legacy_extract_root}'.")
            emit_line(f"[OK] Ancien dossier temporaire supprime: '{legacy_extract_root}'.")
        except OSError as exc:
            if debug:
                debug.log("CLEANUP", f"Suppression ancien temporaire impossible '{legacy_extract_root}': {exc}")
            emit_line(f"[ERROR] Impossible de supprimer '{legacy_extract_root}': {exc}")
    return logs


def process_root(
    root: Path,
    dry_run: bool = False,
    debug: DebugLogger | None = None,
    errors: list[str] | None = None,
    titleid: Optional[str] = None,
) -> None:
    errors = errors if errors is not None else []
    print_status(f"Repertoire de travail: {root}")
    if debug:
        debug.log("ROOT", f"Traitement racine '{root}' (dry_run={dry_run}).")
    top_folders = [
        p for p in root.iterdir() if p.is_dir() and not is_extract_work_dir(p.name)
    ]
    if debug:
        debug.log("ROOT", f"Dossiers detectes: {[p.name for p in top_folders]}")

    if not top_folders:
        print_status("Aucun dossier trouve dans ce repertoire.")
    else:
        for folder in sorted(top_folders, key=lambda p: p.name.lower()):
            try:
                print_status(normalize_folder(folder, dry_run=dry_run, debug=debug, titleid=titleid))
            except Exception as exc:
                record_error(errors, f"Erreur dossier '{folder}'", exc, debug)
                print_status(f"[ERROR] {folder.name}: erreur inattendue, suite du traitement...")

    process_archives(root, dry_run=dry_run, debug=debug, errors=errors, titleid=titleid)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verifie chaque dossier du repertoire cible pour assurer la structure "
            "'<dossier>/contents/0100000000010000/romfs', et traite aussi les archives."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Chemin racine a traiter (par defaut: dossier du script).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les actions sans rien modifier.",
    )
    parser.add_argument(
        "--skip-archives",
        action="store_true",
        help="N'extrait pas les archives; traite uniquement les dossiers deja presents.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Cree un fichier debug.txt avec le detail complet des etapes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    root = Path(args.path).resolve() if args.path else script_dir
    launch_dir = Path.cwd().resolve()
    configure_console_line_by_line()
    enable_windows_ansi()
    debug = DebugLogger(enabled=args.debug, output_dir=launch_dir)
    errors: list[str] = []
    debug.log("MAIN", f"Arguments: path='{args.path}', dry_run={args.dry_run}, skip_archives={args.skip_archives}, debug={args.debug}")
    
    # Load titleID database
    db_path = script_dir / "switch_games.txt"
    database = load_titleid_database(db_path)
    print_status(f"[INFO] Base de données chargée: {len(database)} jeux")
    
    # Check if any folder needs titleID selection
    global selected_titleid
    selected_titleid = None
    
    # Scan folders to detect if any need titleID selection
    top_folders = [
        p for p in root.iterdir() if p.is_dir() and not is_extract_work_dir(p.name)
    ] if root.exists() and root.is_dir() else []
    
    # Also check for archives
    archives = sorted([p for p in root.iterdir() if is_archive(p)], key=lambda p: p.name.lower()) if root.exists() and root.is_dir() else []
    
    needs_selection = False
    for folder in top_folders:
        # Check if folder has romfs/exefs but no titleID in structure
        has_romfs = (folder / "romfs").exists() or any(folder.rglob("romfs"))
        has_exefs = (folder / "exefs").exists() or any(folder.rglob("exefs"))
        has_titleid_structure = any(
            "contents" in str(p.parts) for p in folder.rglob("*")
        )
        
        if (has_romfs or has_exefs) and not has_titleid_structure:
            needs_selection = True
            break
    
    # If there are archives, we also need selection since they might contain mods without titleID
    if archives and database:
        needs_selection = True
    
    # Toujours afficher l'UI si la base de données est chargée et il y a des archives ou dossiers
    if database and (archives or top_folders):
        print_status("\n[INFO] Selection du jeu requise.")
        selected_titleid = select_game_for_folder("mods", database)
        if not selected_titleid:
            print_status("[INFO] Aucun jeu selectionne, annulation du traitement.")
            raise SystemExit("Aucun jeu selectionne par l'utilisateur.")

    if not root.exists() or not root.is_dir():
        debug.log("MAIN", f"Chemin invalide: '{root}'.")
        raise SystemExit(f"Chemin invalide: {root}")

    try:
        if args.skip_archives:
            # Mode explicite: uniquement les dossiers deja presents.
            print_status(f"Repertoire de travail: {root}")
            top_folders = [
                p for p in root.iterdir() if p.is_dir() and not is_extract_work_dir(p.name)
            ]
            for folder in sorted(top_folders, key=lambda p: p.name.lower()):
                try:
                    print_status(normalize_folder(folder, dry_run=args.dry_run, debug=debug, titleid=selected_titleid))
                except Exception as exc:
                    record_error(errors, f"Erreur dossier '{folder}'", exc, debug)
                    print_status(f"[ERROR] {folder.name}: erreur inattendue, suite du traitement...")
            debug.log("MAIN", "Execution terminee en mode --skip-archives.")
        else:
            process_root(root, dry_run=args.dry_run, debug=debug, errors=errors, titleid=selected_titleid)
    except Exception as exc:
        record_error(errors, "Erreur globale execution", exc, debug)
        print_status("[ERROR] Erreur globale inattendue, execution interrompue.")

    if errors:
        print_status("\nWARN_ERROR:")
        for idx, detail in enumerate(errors, start=1):
            print_status(f"{idx}. {detail}")
        debug.log("MAIN", f"WARN_ERROR final: {errors}")
    else:
        print_status("[OK] Traitement termine sans erreur.")

    debug.log("MAIN", "Execution terminee.")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            input("\nAppuie sur Entree pour fermer...")
        except EOFError:
            pass
