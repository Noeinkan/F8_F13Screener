#!/usr/bin/env python3
"""
GUI moderna per process_historical_13f.py
Interfaccia intuitiva con OUTPUT IN TEMPO REALE
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import json
import sys
from datetime import datetime
from src.core.hedge_funds_config import get_total_funds
from src.core.paths import (
    CATALOG_FILE,
    DASHBOARD_DB_FILE,
    PROCESSED_TRACKING_FILE,
    PROCESSING_METRICS_FILE,
)

class FilingProcessorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🏦 13F Filing Processor - Historical Data Manager")
        self.root.geometry("1200x1100")  # Altezza aumentata per ospitare tutti i controlli senza scrollbar
        self.root.resizable(True, True)
        
        # Variabili
        self.mode_var = tk.StringVar(value="catalog")
        self.full_refresh_var = tk.BooleanVar(value=False)
        self.save_csv_var = tk.BooleanVar(value=False)
        self.is_running = False
        self.process = None
        
        # Variabili per progresso
        self.total_items = 0
        self.current_item = 0
        
        # Nuove variabili per ottimizzazioni
        self.rate_var = tk.DoubleVar(value=10.0)
        self.capacity_var = tk.DoubleVar(value=10.0)
        self.workers_var = tk.IntVar(value=1)
        self.use_processes_var = tk.BooleanVar(value=False)
        self.save_interval_var = tk.IntVar(value=5)
        self.start_date_var = tk.StringVar(value="2020-01-01")
        self.end_date_var = tk.StringVar(value=datetime.now().strftime('%Y-%m-%d'))
        self.quiet_var = tk.BooleanVar(value=False)
        
        # Stile
        self.setup_styles()
        
        # UI
        self.create_ui()
        
        # Carica statistiche iniziali
        self.update_stats()
    
    def setup_styles(self):
        """Configura gli stili moderni"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Colori moderni
        bg_color = "#f0f0f0"
        accent_color = "#0066cc"
        success_color = "#28a745"
        danger_color = "#dc3545"
        
        self.root.configure(bg=bg_color)
        
        # Stili custom
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'), background=bg_color)
        style.configure('Subtitle.TLabel', font=('Segoe UI', 11), background=bg_color, foreground='#666')
        style.configure('Section.TLabel', font=('Segoe UI', 12, 'bold'), background=bg_color)
        style.configure('Info.TLabel', font=('Segoe UI', 10), background=bg_color)
        style.configure('Big.TButton', font=('Segoe UI', 11, 'bold'), padding=15)
        style.configure('Accent.TButton', font=('Segoe UI', 10, 'bold'))
    
    def create_ui(self):
        """Crea l'interfaccia utente"""
        
        # ========== HEADER ==========
        header_frame = tk.Frame(self.root, bg="#0066cc", height=80)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)
        
        title = tk.Label(header_frame, text="🏦 13F Filing Processor", 
                        font=('Segoe UI', 20, 'bold'), bg="#0066cc", fg="white")
        title.pack(pady=10)
        
        subtitle = tk.Label(header_frame, text=f"Gestione filing storici per {get_total_funds()} hedge funds", 
                           font=('Segoe UI', 10), bg="#0066cc", fg="#e0e0e0")
        subtitle.pack()
        
        # ========== MAIN CONTENT ==========
        main_frame = tk.Frame(self.root, bg="#f0f0f0")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # ===== LEFT PANEL: CONTROLLI =====
        left_panel = tk.Frame(main_frame, bg="#ffffff", relief=tk.RIDGE, bd=1)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10), pady=0)
        
        # Padding interno
        controls_frame = tk.Frame(left_panel, bg="#ffffff")
        controls_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Titolo sezione
        ttk.Label(controls_frame, text="⚙️ Configurazione", style='Section.TLabel').pack(anchor=tk.W, pady=(0, 10))
        
        # ===== MODALITÀ =====
        mode_frame = tk.LabelFrame(controls_frame, text=" Modalità di Esecuzione ", 
                                   font=('Segoe UI', 10, 'bold'), bg="#ffffff", padx=10, pady=10)
        mode_frame.pack(fill=tk.X, pady=(0, 15))
        
        modes = [
            ("catalog", "📥 Catalog", "Scarica lista filing (veloce, ~5 min)"),
            ("holdings", "📊 Holdings", "Estrae dati dettagliati (lento, ~1-2 ore)"),
            ("full", "🚀 Full Pipeline", "Catalog + Holdings automatico")
        ]
        
        for value, label, desc in modes:
            rb = ttk.Radiobutton(mode_frame, text=label, variable=self.mode_var, value=value)
            rb.pack(anchor=tk.W, pady=2)
            
            desc_label = ttk.Label(mode_frame, text=f"   ↳ {desc}", 
                                  font=('Segoe UI', 8), foreground='#666')
            desc_label.pack(anchor=tk.W, padx=(20, 0))
        
        # ===== OPZIONI =====
        options_frame = tk.LabelFrame(controls_frame, text=" Opzioni Avanzate ", 
                                   font=('Segoe UI', 10, 'bold'), bg="#ffffff", padx=10, pady=10)
        options_frame.pack(fill=tk.X, pady=(0, 15))
        
        refresh_cb = ttk.Checkbutton(options_frame, text="🔄 Full Refresh", 
                                     variable=self.full_refresh_var)
        refresh_cb.pack(anchor=tk.W)
        
        refresh_info = ttk.Label(options_frame, 
                                text="   ↳ Scarica tutto da zero (ignora tracking)",
                                font=('Segoe UI', 8), foreground='#666')
        refresh_info.pack(anchor=tk.W, padx=(20, 0))

        csv_cb = ttk.Checkbutton(options_frame, text="📄 Salva CSV storico (opzionale)",
                     variable=self.save_csv_var)
        csv_cb.pack(anchor=tk.W, pady=(8, 0))

        csv_info = ttk.Label(options_frame,
                     text="   ↳ DuckDB è canonico; abilita solo se ti serve un CSV locale immediato.",
                     font=('Segoe UI', 8), foreground='#666')
        csv_info.pack(anchor=tk.W, padx=(20, 0))
        
        # ===== PARAMETRI OTTIMIZZAZIONE =====
        optimization_frame = tk.LabelFrame(controls_frame, text=" 🚀 Parametri Ottimizzazione ", 
                                   font=('Segoe UI', 10, 'bold'), bg="#ffffff", padx=10, pady=10)
        optimization_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Rate Limiting
        rate_frame = tk.Frame(optimization_frame, bg="#ffffff")
        rate_frame.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(rate_frame, text="Rate Limit (req/sec):", font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        rate_spin = tk.Spinbox(rate_frame, from_=1, to=20, textvariable=self.rate_var, width=5, font=('Segoe UI', 9))
        rate_spin.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        
        ttk.Label(rate_frame, text="Capacity:", font=('Segoe UI', 9)).grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        capacity_spin = tk.Spinbox(rate_frame, from_=1, to=50, textvariable=self.capacity_var, width=5, font=('Segoe UI', 9))
        capacity_spin.grid(row=0, column=3, sticky=tk.W, padx=(5, 0))
        
        rate_info = ttk.Label(optimization_frame, 
                             text="   ↳ Limite richieste SEC (10/sec raccomandato). Capacity per burst.",
                             font=('Segoe UI', 8), foreground='#666')
        rate_info.pack(anchor=tk.W, padx=(0, 0))
        
        # Parallelismo
        parallel_frame = tk.Frame(optimization_frame, bg="#ffffff")
        parallel_frame.pack(fill=tk.X, pady=(5, 8))
        
        ttk.Label(parallel_frame, text="Workers:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        workers_spin = tk.Spinbox(parallel_frame, from_=1, to=16, textvariable=self.workers_var, width=5, font=('Segoe UI', 9))
        workers_spin.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        
        processes_cb = ttk.Checkbutton(parallel_frame, text="Usa Processi", variable=self.use_processes_var)
        processes_cb.grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        
        parallel_info = ttk.Label(optimization_frame, 
                                 text="   ↳ Workers concorrenti. Processi per CPU-intensive, Thread per I/O.",
                                 font=('Segoe UI', 8), foreground='#666')
        parallel_info.pack(anchor=tk.W, padx=(0, 0))
        
        # Salvataggio
        save_frame = tk.Frame(optimization_frame, bg="#ffffff")
        save_frame.pack(fill=tk.X, pady=(5, 8))
        
        ttk.Label(save_frame, text="Save Interval:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        save_spin = tk.Spinbox(save_frame, from_=1, to=20, textvariable=self.save_interval_var, width=5, font=('Segoe UI', 9))
        save_spin.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        
        save_info = ttk.Label(optimization_frame, 
                             text="   ↳ Salva tracking ogni N fondi processati (riduce I/O disco).",
                             font=('Segoe UI', 8), foreground='#666')
        save_info.pack(anchor=tk.W, padx=(0, 0))
        
        # Date Range
        date_frame = tk.Frame(optimization_frame, bg="#ffffff")
        date_frame.pack(fill=tk.X, pady=(5, 8))
        
        ttk.Label(date_frame, text="Start Date:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        start_entry = ttk.Entry(date_frame, textvariable=self.start_date_var, width=12, font=('Segoe UI', 9))
        start_entry.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))
        
        ttk.Label(date_frame, text="End Date:", font=('Segoe UI', 9)).grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        end_entry = ttk.Entry(date_frame, textvariable=self.end_date_var, width=12, font=('Segoe UI', 9))
        end_entry.grid(row=0, column=3, sticky=tk.W, padx=(5, 0))
        
        date_info = ttk.Label(optimization_frame, 
                             text="   ↳ Range temporale (YYYY-MM-DD). Default: ultimi 5 anni.",
                             font=('Segoe UI', 8), foreground='#666')
        date_info.pack(anchor=tk.W, padx=(0, 0))
        
        # Quiet Mode
        quiet_cb = ttk.Checkbutton(optimization_frame, text="🔇 Modalità Silenziosa", variable=self.quiet_var)
        quiet_cb.pack(anchor=tk.W, pady=(5, 0))
        
        quiet_info = ttk.Label(optimization_frame, 
                              text="   ↳ Output minimo (solo errori e riepilogo).",
                              font=('Segoe UI', 8), foreground='#666')
        quiet_info.pack(anchor=tk.W, padx=(20, 0))
        
        # Pulsante reset
        reset_btn = tk.Button(optimization_frame, text="🔄 Ripristina Default", 
                             command=self.reset_optimization_defaults,
                             font=('Segoe UI', 9), bg="#6c757d", fg="white",
                             activebackground="#5a6268", relief=tk.RAISED, bd=1)
        reset_btn.pack(anchor=tk.W, pady=(10, 0))
        
        # ===== STATISTICHE =====
        stats_frame = tk.LabelFrame(controls_frame, text=" 📊 Statistiche ", 
                                   font=('Segoe UI', 10, 'bold'), bg="#ffffff", padx=10, pady=10)
        stats_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.stats_text = tk.Text(stats_frame, height=6, font=('Consolas', 9), 
                                 bg="#f8f9fa", relief=tk.FLAT, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.X)
        
        # ===== PULSANTI AZIONE =====
        buttons_frame = tk.Frame(controls_frame, bg="#ffffff")
        buttons_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.start_btn = tk.Button(buttons_frame, text="▶️ AVVIA PROCESSO", 
                                   command=self.start_process,
                                   font=('Segoe UI', 12, 'bold'), 
                                   bg="#28a745", fg="white",
                                   activebackground="#218838",
                                   relief=tk.RAISED, bd=2,
                                   cursor="hand2", pady=12)
        self.start_btn.pack(fill=tk.X, pady=(0, 8))
        
        self.stop_btn = tk.Button(buttons_frame, text="⏹️ FERMA", 
                                  command=self.stop_process,
                                  font=('Segoe UI', 10, 'bold'), 
                                  bg="#dc3545", fg="white",
                                  activebackground="#c82333",
                                  relief=tk.RAISED, bd=2,
                                  cursor="hand2", state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X)
        
        # ===== RIGHT PANEL: OUTPUT LOG =====
        right_panel = tk.Frame(main_frame, bg="#ffffff", relief=tk.RIDGE, bd=1)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # Progress section
        progress_frame = tk.Frame(right_panel, bg="#2c3e50", height=60)
        progress_frame.pack(fill=tk.X)
        progress_frame.pack_propagate(False)
        
        # Counter label
        self.progress_counter_label = tk.Label(progress_frame, text="🔢 Progresso: In attesa...", 
                                              font=('Segoe UI', 9, 'bold'), bg="#2c3e50", fg="white")
        self.progress_counter_label.pack(side=tk.TOP, padx=10, pady=5, anchor=tk.W)
        
        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", length=400)
        self.progress_bar.pack(side=tk.TOP, padx=10, pady=(0,5), fill=tk.X, expand=True)
        self.progress_bar['value'] = 0
        
        # Header log
        log_header = tk.Frame(right_panel, bg="#2c3e50", height=35)
        log_header.pack(fill=tk.X)
        log_header.pack_propagate(False)
        
        tk.Label(log_header, text="📋 Output in tempo reale", 
                font=('Segoe UI', 10, 'bold'), bg="#2c3e50", fg="white").pack(side=tk.LEFT, padx=10, pady=8)
        
        # Log area con scrollbar
        log_frame = tk.Frame(right_panel, bg="#ffffff")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, 
                                                  font=('Consolas', 9),
                                                  bg="#1e1e1e", fg="#d4d4d4",
                                                  insertbackground="white",
                                                  relief=tk.FLAT,
                                                  wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Tag per colori
        self.log_text.tag_config("success", foreground="#4ec9b0")
        self.log_text.tag_config("error", foreground="#f48771")
        self.log_text.tag_config("warning", foreground="#dcdcaa")
        self.log_text.tag_config("info", foreground="#569cd6")
        
        # ========== FOOTER ==========
        footer = tk.Frame(self.root, bg="#e0e0e0", height=30)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)
        
        self.status_label = tk.Label(footer, text="✅ Pronto", 
                                     font=('Segoe UI', 9), bg="#e0e0e0", fg="#333")
        self.status_label.pack(side=tk.LEFT, padx=10, pady=5)
    
    def reset_optimization_defaults(self):
        """Ripristina i valori di default per i parametri di ottimizzazione"""
        self.rate_var.set(10.0)
        self.capacity_var.set(10.0)
        self.workers_var.set(1)
        self.use_processes_var.set(False)
        self.save_interval_var.set(5)
        self.start_date_var.set("2020-01-01")
        self.end_date_var.set(datetime.now().strftime('%Y-%m-%d'))
        self.quiet_var.set(False)
        self.save_csv_var.set(False)
        self.update_stats()
    
    def update_stats(self):
        """Aggiorna le statistiche"""
        self.stats_text.delete(1.0, tk.END)
        
        stats = []
        stats.append(f"🏢 Hedge funds: {get_total_funds()}")
        
        # Catalogo
        if os.path.exists(CATALOG_FILE):
            try:
                with open(CATALOG_FILE, 'r') as f:
                    data = json.load(f)
                    stats.append(f"📄 Filing catalogati: {data.get('total_filings', 0)}")
                    stats.append(f"🆕 Nuovi: {data.get('new_filings', 0)}")
                    stats.append(f"📅 Ultimo update: {data.get('generated_at', 'N/A')[:10]}")
            except:
                stats.append("📄 Catalogo: Non disponibile")
        else:
            stats.append("📄 Catalogo: Non ancora creato")
        
        # DuckDB canonico
        if os.path.exists(DASHBOARD_DB_FILE):
            size_mb = os.path.getsize(DASHBOARD_DB_FILE) / (1024*1024)
            stats.append(f"🗄️ DuckDB canonico: {size_mb:.1f} MB")
        else:
            stats.append("🗄️ DuckDB canonico: Non ancora creato")
        
        # Tracking
        if os.path.exists(PROCESSED_TRACKING_FILE):
            try:
                with open(PROCESSED_TRACKING_FILE, 'r') as f:
                    data = json.load(f)
                    stats.append(f"✅ Processati: {data.get('total_processed', 0)}")
            except:
                pass
        
        # Impostazioni ottimizzazione correnti
        stats.append("")
        stats.append("⚙️ Impostazioni Ottimizzazione:")
        stats.append(f"  🚀 Rate: {self.rate_var.get()}/sec (cap: {self.capacity_var.get()})")
        stats.append(f"  👥 Workers: {self.workers_var.get()} ({'Processi' if self.use_processes_var.get() else 'Thread'})")
        stats.append(f"  💾 Save Interval: {self.save_interval_var.get()}")
        stats.append(f"  📄 CSV storico: {'Sì' if self.save_csv_var.get() else 'No'}")
        stats.append(f"  📅 Range: {self.start_date_var.get()} → {self.end_date_var.get()}")
        stats.append(f"  🔇 Quiet: {'Sì' if self.quiet_var.get() else 'No'}")
        
        self.stats_text.insert(1.0, "\n".join(stats))
        self.stats_text.config(state=tk.DISABLED)
    
    def reset_progress(self, mode):
        """Reset barra progresso e counter"""
        self.total_items = 0
        self.current_item = 0
        self.progress_bar['value'] = 0
        self.progress_counter_label.config(text="🔢 Progresso: In attesa...")
    
    def update_progress(self, message):
        """Aggiorna barra progresso e counter se trova pattern"""
        import re
        
        # Pattern per [current/total] (tqdm style)
        tqdm_match = re.search(r'\[(\d+)/(\d+)\]', message)
        if tqdm_match:
            try:
                current = int(tqdm_match.group(1))
                total = int(tqdm_match.group(2))
                self.current_item = current
                self.total_items = total
                percentage = (current / total) * 100 if total > 0 else 0
                self.progress_bar['value'] = percentage
                self.progress_counter_label.config(text=f"🔢 Progresso: {current}/{total} ({percentage:.1f}%)")
                return
            except (ValueError, IndexError):
                pass
        
        # Pattern per 🏦 [current/total] (fase holdings)
        fund_match = re.search(r'🏦 \[(\d+)/(\d+)\]', message)
        if fund_match:
            try:
                current = int(fund_match.group(1))
                total = int(fund_match.group(2))
                self.current_item = current
                self.total_items = total
                percentage = (current / total) * 100 if total > 0 else 0
                self.progress_bar['value'] = percentage
                self.progress_counter_label.config(text=f"🔢 Funds: {current}/{total} ({percentage:.1f}%)")
                return
            except (ValueError, IndexError):
                pass
        
        # Pattern per "Successi: X" o simili riepiloghi
        success_match = re.search(r'Successi:\s*(\d+)', message, re.IGNORECASE)
        if success_match:
            try:
                current = int(success_match.group(1))
                self.current_item = current
                if self.total_items > 0:
                    percentage = (current / self.total_items) * 100
                    self.progress_bar['value'] = percentage
                    self.progress_counter_label.config(text=f"🔢 Successi: {current}/{self.total_items} ({percentage:.1f}%)")
                else:
                    self.progress_counter_label.config(text=f"🔢 Successi: {current}")
                return
            except (ValueError, IndexError):
                pass
        
        # Pattern per "Da processare: X" per impostare total
        total_match = re.search(r'Da processare:\s*(\d+)', message, re.IGNORECASE)
        if total_match:
            try:
                self.total_items = int(total_match.group(1))
                self.progress_counter_label.config(text=f"🔢 Da processare: {self.total_items}")
                return
            except (ValueError, IndexError):
                pass
    
    def log(self, message, tag=None):
        """Aggiungi messaggio al log"""
        # Aggiorna progresso
        self.update_progress(message)
        
        # Stampa anche nel terminal di VS Code
        print(message)
        
        self.log_text.config(state=tk.NORMAL)
        if tag:
            self.log_text.insert(tk.END, message + "\n", tag)
        else:
            self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()
    
    def start_process(self):
        """Avvia il processo selezionato"""
        if self.is_running:
            messagebox.showwarning("Attenzione", "Un processo è già in esecuzione!")
            return
        
        mode = self.mode_var.get()
        full_refresh = self.full_refresh_var.get()
        
        # Conferma per holdings/full (mostra stima dinamica se possibile)
        if mode in ['holdings', 'full']:
            msg = f"Modalità '{mode}' selezionata.\n\n"

            # Calcola stima dinamica basata su file locali (se disponibili)
            try:
                estimate_str = self.compute_estimated_time(mode, full_refresh)
                msg += f"Stima: {estimate_str}\n"
            except Exception:
                # Fallback testuale se qualcosa va storto
                if mode == 'holdings':
                    msg += "Questo processo può richiedere 1-2 ore.\n"
                else:
                    msg += "Questo processo può richiedere 2-3 ore.\n"

            msg += "\nVuoi procedere?"

            if not messagebox.askyesno("Conferma", msg):
                return
        
        # Disabilita controlli
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED, bg="#6c757d")
        self.stop_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"⏳ In esecuzione: {mode}...", fg="#ff6600")
        
        # Reset progresso
        self.reset_progress(mode)
        
        # Pulisci log
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        self.log(f"{'='*70}", "info")
        self.log(f"🚀 AVVIO PROCESSO: {mode.upper()}", "info")
        self.log(f"{'='*70}", "info")
        self.log(f"⏰ Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "info")
        self.log(f"⚙️  Full Refresh: {'Sì' if full_refresh else 'No'}", "info")
        self.log(f"🚀 Rate Limit: {self.rate_var.get()}/sec (capacity: {self.capacity_var.get()})", "info")
        self.log(f"👥 Workers: {self.workers_var.get()} ({'Processi' if self.use_processes_var.get() else 'Thread'})", "info")
        self.log(f"💾 Save Interval: {self.save_interval_var.get()} fondi", "info")
        self.log(f"📄 CSV storico: {'Sì (--save-csv)' if self.save_csv_var.get() else 'No (DuckDB only)'}", "info")
        self.log(f"📅 Date Range: {self.start_date_var.get()} → {self.end_date_var.get()}", "info")
        self.log(f"🔇 Quiet Mode: {'Sì' if self.quiet_var.get() else 'No'}", "info")
        self.log("")
        
        # Avvia in thread separato
        thread = threading.Thread(target=self.run_process, args=(mode, full_refresh))
        thread.daemon = True
        thread.start()
    
    def run_process(self, mode, full_refresh):
        """Esegue il processo (in thread separato)"""
        try:
            # Costruisci comando
            cmd = [sys.executable, "src/cli/process_historical_13f.py", mode]
            
            if full_refresh and mode in ['catalog', 'full']:
                cmd.append("--full-refresh")
            
            # Aggiungi --yes per modalità che richiedono conferma
            if mode in ['full', 'holdings']:
                cmd.append("--yes")
                if self.save_csv_var.get():
                    cmd.append("--save-csv")
            
            # Parametri ottimizzazione
            cmd.extend(["--rate", str(self.rate_var.get())])
            cmd.extend(["--capacity", str(self.capacity_var.get())])
            cmd.extend(["--workers", str(self.workers_var.get())])
            if self.use_processes_var.get():
                cmd.append("--use-processes")
            cmd.extend(["--save-interval", str(self.save_interval_var.get())])
            cmd.extend(["--start-date", self.start_date_var.get()])
            cmd.extend(["--end-date", self.end_date_var.get()])
            if self.quiet_var.get():
                cmd.append("--quiet")
            
            self.log(f"$ {' '.join(cmd)}\n", "warning")
            
            # Esegui processo con output in tempo reale
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
            )
            
            # Leggi output linea per linea
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    # Colora output
                    if '✅' in line or 'success' in line.lower():
                        self.log(line.rstrip(), "success")
                    elif '❌' in line or 'error' in line.lower() or 'failed' in line.lower():
                        self.log(line.rstrip(), "error")
                    elif '⚠️' in line or 'warning' in line.lower():
                        self.log(line.rstrip(), "warning")
                    else:
                        self.log(line.rstrip())
            
            # Attendi completamento
            self.process.wait()
            
            # Risultato
            if self.process.returncode == 0:
                self.log("\n" + "="*70, "success")
                self.log("✅ PROCESSO COMPLETATO CON SUCCESSO!", "success")
                self.log("="*70 + "\n", "success")
                self.root.after(0, lambda: self.status_label.config(text="✅ Completato!", fg="#28a745"))
                self.root.after(0, lambda: messagebox.showinfo("Successo", f"Processo '{mode}' completato!"))
            else:
                self.log("\n" + "="*70, "error")
                self.log(f"❌ PROCESSO TERMINATO CON ERRORI (exit code: {self.process.returncode})", "error")
                self.log("="*70 + "\n", "error")
                self.root.after(0, lambda: self.status_label.config(text="❌ Errore", fg="#dc3545"))
                self.root.after(0, lambda: messagebox.showerror("Errore", f"Processo '{mode}' fallito!"))
            
        except Exception as e:
            self.log(f"\n❌ ERRORE: {str(e)}", "error")
            self.root.after(0, lambda: self.status_label.config(text="❌ Errore", fg="#dc3545"))
            self.root.after(0, lambda: messagebox.showerror("Errore", str(e)))
        
        finally:
            # Riabilita controlli
            self.root.after(0, self.process_finished)
    
    def stop_process(self):
        """Ferma il processo in esecuzione"""
        if self.process and self.process.poll() is None:
            if messagebox.askyesno("Conferma", "Vuoi davvero interrompere il processo?"):
                self.process.terminate()
                self.log("\n⏹️ PROCESSO INTERROTTO DALL'UTENTE", "warning")
                self.status_label.config(text="⏹️ Interrotto", fg="#ff6600")
    
    def process_finished(self):
        """Chiamato quando il processo termina"""
        self.is_running = False
        self.process = None
        self.start_btn.config(state=tk.NORMAL, bg="#28a745")
        self.stop_btn.config(state=tk.DISABLED)
        self.update_stats()
        
        # Reset progresso
        self.progress_bar['value'] = 100 if self.total_items > 0 and self.current_item >= self.total_items else 0
        self.progress_counter_label.config(text=f"🔢 Completato: {self.current_item}/{self.total_items}" if self.total_items > 0 else "🔢 Completato")

    def compute_estimated_time(self, mode: str, full_refresh: bool) -> str:
        """Calcola una stima di durata in base ai file locali se disponibili.

        Ritorna una stringa leggibile (es. '~45 minuti' o '1-2 ore').
        Usa `historical_13f_catalog_5years.json` per contare i filing e
        `processed_filings_tracking.json` per escludere quelli già processati.
        Se i file non esistono torna una stima generica.
        """
        try:
            # Default estimates (fallback)
            if mode == 'holdings':
                per_filing_seconds = 9  # stima media: 9s per filing (download+parse)
            else:
                # full = catalog (rapido) + holdings
                per_filing_seconds = 9

            catalog_path = CATALOG_FILE
            tracking_path = PROCESSED_TRACKING_FILE

            total_to_process = None

            if mode == 'catalog':
                # catalog step is proportional al numero di funds
                from hedge_funds_config import get_total_funds
                # catalog takes ~0.11s per fund for API call (rate limit backoff)
                # But with higher rate, it's faster
                rate = self.rate_var.get()
                base_time_per_fund = max(0.11, 1.0 / rate)  # minimum time per request
                est_seconds = get_total_funds() * base_time_per_fund
                # convert to human string
                if est_seconds < 60:
                    return f"~{int(est_seconds)} secondi (solo catalog)"
                else:
                    minutes = est_seconds / 60
                    return f"~{minutes:.1f} minuti (solo catalog)"

            # For holdings and full, try to read catalog to know number of filings
            if os.path.exists(catalog_path):
                with open(catalog_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    filings = data.get('filings', [])
                    total_filings = len(filings)
            else:
                total_filings = None

            # Prefer measured metrics if available
            metrics_path = PROCESSING_METRICS_FILE
            if os.path.exists(metrics_path):
                try:
                    with open(metrics_path, 'r', encoding='utf-8') as mf:
                        m = json.load(mf)
                        avg = m.get('avg')
                        if avg and avg > 0:
                            per_filing_seconds = float(avg)
                except Exception:
                    pass

            processed = 0
            if os.path.exists(tracking_path):
                try:
                    with open(tracking_path, 'r', encoding='utf-8') as f:
                        t = json.load(f)
                        processed = len(t.get('processed_accession_numbers', []))
                except Exception:
                    processed = 0

            if total_filings is None:
                # Not available -> return generic message
                if mode == 'holdings':
                    return "~1-2 ore (dipende dal numero di filing e dalla rete)"
                else:
                    return "~2-3 ore (catalog + holdings; dipende dal numero di filing)"

            # Calculate remaining filings to process
            if full_refresh:
                remaining = total_filings
            else:
                remaining = max(0, total_filings - processed)

            # Estimate seconds: per_filing_seconds * remaining / workers
            workers = self.workers_var.get()
            est_seconds = (per_filing_seconds * remaining) / workers

            # Add catalog time for full mode
            if mode == 'full':
                from hedge_funds_config import get_total_funds
                rate = self.rate_var.get()
                base_time_per_fund = max(0.11, 1.0 / rate)
                est_seconds += get_total_funds() * base_time_per_fund

            # Build human readable
            if est_seconds < 60:
                return f"~{int(est_seconds)} secondi (circa {remaining} filing)"
            elif est_seconds < 3600:
                minutes = est_seconds / 60
                return f"~{int(minutes)} minuti (circa {remaining} filing)"
            else:
                hours = est_seconds / 3600
                if hours < 2:
                    return f"~{hours:.1f} ore (circa {remaining} filing)"
                else:
                    return f"~{int(hours)} ore (circa {remaining} filing)"
        except Exception:
            # Fallback generic
            if mode == 'holdings':
                return "~1-2 ore (stima generica)"
            else:
                return "~2-3 ore (stima generica)"

def main():
    root = tk.Tk()
    app = FilingProcessorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
