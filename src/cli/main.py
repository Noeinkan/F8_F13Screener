"""
13F Alert System - Main orchestration
Refactored modular version with clean separation of concerns
"""
import json
import logging
import threading
import time
import sys
import os
import subprocess
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.core.config import Config
from src.core.dashboard_storage import DashboardStorage
from src.core.sec_client import SECClient
from src.core.parser import HoldingsParser
from src.core.notifier import TelegramNotifier
from src.core.storage import Storage
from src.core.diff import compute_portfolio_diff
from src.core.telegram_commands import TelegramCommandHandler
from src.core.paths import DASHBOARD_DB_FILE

def launch_telegram_viewer() -> bool:
    """Launch Telegram viewer in a separate window"""
    try:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        viewer_path = os.path.join(base_dir, 'src', 'gui', 'telegram_viewer.py')
        batch_path = os.path.join(base_dir, 'scripts', 'launch_viewer.bat')
        
        if not os.path.exists(viewer_path):
            print(f"⚠️  Viewer non trovato: {viewer_path}")
            return False
        
        # On Windows, try batch file first (more reliable)
        if sys.platform == 'win32' and os.path.exists(batch_path):
            try:
                subprocess.Popen(
                    [batch_path],
                    shell=True,
                    cwd=base_dir
                )
                print("✓ Telegram Viewer avviato (via batch)")
                return True
            except Exception as e:
                print(f"Fallback da batch: {e}")
        
        # Fallback or other OS
        if sys.platform == 'win32':
            # Use pythonw.exe to avoid console window
            python_exe = sys.executable.replace('python.exe', 'pythonw.exe')
            if not os.path.exists(python_exe):
                python_exe = sys.executable
            
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                [python_exe, viewer_path],
                creationflags=DETACHED_PROCESS,
                shell=False,
                cwd=base_dir
            )
        else:
            subprocess.Popen(
                [sys.executable, viewer_path],
                close_fds=True,
                cwd=base_dir
            )
        
        print("✓ Telegram Viewer avviato")
        return True
        
    except Exception as e:
        print(f"⚠️  Errore avvio Telegram Viewer: {e}")
        return False


# Setup logging with rotation
def setup_logging(log_file: Path) -> logging.Logger:
    """Configure logging with rotating file handler"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)

    # Rotating file handler (10MB max, keep 5 backups)
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)
        print(f"Log file: {log_file}")
    except Exception as e:
        print(f"Warning: Could not create log file: {e}")

    logger.addHandler(console_handler)
    return logger


class FilingProcessor:
    """Main processor for 13F filings"""

    def __init__(self, config: Config):
        self.config = config
        self.sec_client = SECClient(
            config.sec_user_agent,
            config.max_retries,
            config.retry_delay
        )
        self.parser = HoldingsParser(config.sec_user_agent)
        self.notifier = TelegramNotifier(
            config.telegram_bot_token,
            config.telegram_chat_id,
            config.max_retries,
            config.retry_delay
        )
        self.storage = Storage(config.holdings_db)
        self.dashboard_storage = DashboardStorage(DASHBOARD_DB_FILE)
        self.logger = logging.getLogger(__name__)
        self.runtime_state = self._load_runtime_state()

    def _load_runtime_state(self) -> dict:
        if not self.config.last_check_file.exists():
            return {}

        try:
            with self.config.last_check_file.open('r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            self.logger.warning(f"Impossibile leggere state file realtime: {e}")
            return {}

    def _save_runtime_state(self) -> None:
        try:
            self.config.last_check_file.parent.mkdir(parents=True, exist_ok=True)
            with self.config.last_check_file.open('w', encoding='utf-8') as f:
                json.dump(self.runtime_state, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Impossibile salvare state file realtime: {e}")

    @staticmethod
    def _build_entry_id(source: str, cik: str, accession_number: str, fallback: str) -> str:
        if accession_number and accession_number != 'N/A':
            return f"filing:{cik}:{accession_number}"
        return fallback

    @staticmethod
    def _build_seen_candidates(source: str, cik: str, accession_number: str, fallback: str) -> set[str]:
        if accession_number and accession_number != 'N/A':
            return {
                f"filing:{cik}:{accession_number}",
                f"submissions:{cik}:{accession_number}",
                f"feed:{cik}:{accession_number}",
            }
        return {fallback, f"{source}:{fallback}"}

    def _needs_holdings_backfill(self, accession_number: str) -> bool:
        if not accession_number or accession_number == 'N/A':
            return False

        sqlite_has_holdings = self.storage.has_holdings_for_accession(accession_number)
        if not sqlite_has_holdings:
            return True

        try:
            return not self.dashboard_storage.has_holdings_for_accession(accession_number)
        except Exception as e:
            self.logger.warning(
                "DuckDB dashboard temporaneamente non accessibile per %s: %s. "
                "Backfill dashboard rinviato al prossimo ciclo utile.",
                accession_number,
                e,
            )
            return False

    def process_filings_cycle(self):
        """Primary filings cycle: submissions endpoint first, Atom feed fallback second."""
        self.process_submissions()
        if self.config.enable_atom_fallback:
            self.process_feed_fallback()

    def process_submissions(self):
        """Process recent filings discovered via SEC submissions endpoint."""
        self.logger.info("\n%s", "=" * 60)
        self.logger.info("Controllo submissions alle %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        seen_filings = self.storage.get_seen_filings(limit=2000)
        bootstrap_mode = not self.runtime_state.get('submissions_bootstrapped', False)
        if bootstrap_mode:
            self.logger.info(
                "Bootstrap submissions attivo: backfill DB e seed dei filing recenti senza invio Telegram"
            )

        stats = {
            'total_checked': 0,
            'already_seen': 0,
            'bootstrapped': 0,
            'matched': 0,
            'filtered': 0,
            'sent': 0,
            'failed': 0,
        }

        for cik, fund_name in self.config.hedge_funds_cik.items():
            filings = self.sec_client.fetch_recent_13f_for_cik(
                cik,
                max_entries=self.config.submissions_recent_limit,
            )

            for filing in filings:
                stats['total_checked'] += 1

                accession_number = filing.get('accession_number', '')
                filing_url = filing.get('filing_url', '')
                filer_name = filing.get('filer_name', '') or fund_name
                filing_date = filing.get('filing_date', '')
                acceptance_datetime = filing.get('acceptance_datetime', '') or filing_date

                entry_id = self._build_entry_id(
                    source='submissions',
                    cik=cik,
                    accession_number=accession_number,
                    fallback=f"submissions:{cik}:{filing_date}:{filing.get('primary_document', '')}",
                )
                seen_candidates = self._build_seen_candidates(
                    source='submissions',
                    cik=cik,
                    accession_number=accession_number,
                    fallback=f"submissions:{cik}:{filing_date}:{filing.get('primary_document', '')}",
                )

                if any(candidate in seen_filings for candidate in seen_candidates):
                    if self._needs_holdings_backfill(accession_number):
                        self.logger.info(
                            "Backfill holdings per filing gia visto %s (%s)",
                            accession_number,
                            fund_name,
                        )
                        self._process_holdings(
                            filing_url,
                            filer_name,
                            fund_name,
                            cik,
                            filing_date,
                            acceptance_datetime=acceptance_datetime,
                        )
                    stats['already_seen'] += 1
                    continue

                if bootstrap_mode:
                    self.storage.mark_filing_seen(
                        entry_id,
                        filer_name,
                        cik,
                        filing_date,
                        acceptance_datetime=acceptance_datetime,
                        matched=True,
                    )
                    if self._needs_holdings_backfill(accession_number):
                        self.logger.info(
                            "Bootstrap backfill holdings per %s (%s)",
                            accession_number,
                            fund_name,
                        )
                        self._process_holdings(
                            filing_url,
                            filer_name,
                            fund_name,
                            cik,
                            filing_date,
                            acceptance_datetime=acceptance_datetime,
                        )
                    seen_filings.add(entry_id)
                    stats['bootstrapped'] += 1
                    continue

                # Mark as seen before outbound notification to avoid duplicate alerts.
                self.storage.mark_filing_seen(
                    entry_id,
                    filer_name,
                    cik,
                    filing_date,
                    acceptance_datetime=acceptance_datetime,
                    matched=False,
                )

                stats['matched'] += 1
                self.storage.mark_filing_seen(
                    entry_id,
                    filer_name,
                    cik,
                    filing_date,
                    acceptance_datetime=acceptance_datetime,
                    matched=True,
                )

                holdings_saved, portfolio_diff = self._process_holdings(
                    filing_url,
                    filer_name,
                    fund_name,
                    cik,
                    filing_date,
                    acceptance_datetime=acceptance_datetime,
                )

                if self.notifier.send_filing_alert(
                    fund_name,
                    filer_name,
                    acceptance_datetime,
                    filing_url,
                    holdings_saved,
                    portfolio_diff,
                ):
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1

                seen_filings.add(entry_id)

            time.sleep(self.config.submissions_request_delay_seconds)

        self.logger.info(
            "📊 Submissions: %s totali | %s già visti | %s bootstrap | %s matched | %s inviati | %s falliti",
            stats['total_checked'],
            stats['already_seen'],
            stats['bootstrapped'],
            stats['matched'],
            stats['sent'],
            stats['failed'],
        )

        if bootstrap_mode:
            self.runtime_state['submissions_bootstrapped'] = True
            self.runtime_state['submissions_bootstrapped_at'] = datetime.utcnow().isoformat(timespec='seconds') + 'Z'
            self._save_runtime_state()

        self.storage.update_statistics(
            total_checked=stats['total_checked'] - stats['already_seen'],
            matched=stats['matched'],
            filtered=stats['filtered'],
        )

    def process_feed_fallback(self):
        """Process the current RSS feed as fallback/secondary monitoring."""
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"Controllo feed fallback alle {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Fetch feed
        feed = self.sec_client.fetch_13f_feed(self.config.rss_url)

        if not feed.entries:
            self.logger.warning("Feed vuoto o non disponibile")
            return

        # Get seen filings from database
        seen_filings = self.storage.get_seen_filings()

        # Statistics
        stats = {
            'total_checked': 0,
            'already_seen': 0,
            'matched': 0,
            'filtered': 0,
            'sent': 0,
            'failed': 0
        }

        # Process each entry
        for entry in feed.entries:
            try:
                # Extract information
                title = str(entry.get('title', '') or '')
                filer_name = self.sec_client.extract_filer_name_from_title(title)
                filing_date = str(entry.get('updated', 'Data N/A') or 'Data N/A')
                filing_url = str(entry.get('link', '') or '')

                # Extract CIK
                cik = self.sec_client.extract_cik_from_link(filing_url)
                accession_number = self.sec_client.extract_accession_number(filing_url)
                entry_fallback_id = str(getattr(entry, 'id', '') or '')

                entry_id = self._build_entry_id(
                    source='feed',
                    cik=cik,
                    accession_number=accession_number,
                    fallback=entry_fallback_id,
                )
                seen_candidates = self._build_seen_candidates(
                    source='feed',
                    cik=cik,
                    accession_number=accession_number,
                    fallback=entry_fallback_id,
                )
                stats['total_checked'] += 1

                # Skip if already seen
                if any(candidate in seen_filings for candidate in seen_candidates):
                    matched_fund = self.config.hedge_funds_cik.get(cik.zfill(10)) or self.config.hedge_funds_cik.get(cik)
                    if matched_fund and self._needs_holdings_backfill(accession_number):
                        self.logger.info(
                            "Backfill holdings da feed fallback per filing gia visto %s (%s)",
                            accession_number,
                            matched_fund,
                        )
                        self._process_holdings(
                            filing_url,
                            filer_name,
                            matched_fund,
                            cik,
                            filing_date,
                            acceptance_datetime=filing_date,
                        )
                    stats['already_seen'] += 1
                    continue

                # CRITICAL FIX: Mark as seen immediately after parsing
                # This prevents re-processing if notification fails
                self.storage.mark_filing_seen(
                    entry_id,
                    filer_name,
                    cik,
                    filing_date,
                    acceptance_datetime=filing_date,
                    matched=False,
                )

                # Check if matches our filter
                is_match, matched_fund = self.sec_client.should_notify(
                    filer_name,
                    filing_url,
                    self.config.hedge_funds_cik
                )

                if not is_match:
                    stats['filtered'] += 1
                    self.logger.debug(f"Skippato (filtro CIK): {filer_name} (CIK: {cik})")
                    continue

                # Match found!
                stats['matched'] += 1
                self.logger.info(f"✓ MATCH: {matched_fund} - {filer_name}")

                # Update as matched
                self.storage.mark_filing_seen(
                    entry_id,
                    filer_name,
                    cik,
                    filing_date,
                    acceptance_datetime=filing_date,
                    matched=True,
                )

                # Process holdings
                holdings_saved, portfolio_diff = self._process_holdings(
                    filing_url,
                    filer_name,
                    matched_fund,
                    cik,
                    filing_date,
                    acceptance_datetime=filing_date,
                )

                # Send notification (failure here won't cause re-processing)
                if self.notifier.send_filing_alert(
                    matched_fund,
                    filer_name,
                    filing_date,
                    filing_url,
                    holdings_saved,
                    portfolio_diff,
                ):
                    stats['sent'] += 1
                else:
                    stats['failed'] += 1

            except Exception as e:
                self.logger.error(f"Errore processamento entry: {e}", exc_info=True)

        # Log summary
        self.logger.info(
            f"📊 Riepilogo: {stats['total_checked']} totali | "
            f"{stats['already_seen']} già visti | "
            f"{stats['matched']} matched | "
            f"{stats['sent']} inviati | "
            f"{stats['filtered']} filtrati | "
            f"{stats['failed']} falliti"
        )

        # Update statistics (only new filings)
        self.storage.update_statistics(
            total_checked=stats['total_checked'] - stats['already_seen'],
            matched=stats['matched'],
            filtered=stats['filtered']
        )

    def _process_holdings(
        self,
        filing_url: str,
        filer_name: str,
        fund_name: str,
        cik: str,
        filing_date: str,
        acceptance_datetime: str = '',
    ):
        """
        Process and save holdings for a filing.

        Returns:
            Tuple (holdings_saved: bool, portfolio_diff: dict | None)
        """
        try:
            self.logger.info(f"Processamento holdings per: {filer_name}")

            # Extract accession number
            accession_number = self.sec_client.extract_accession_number(filing_url)

            # Get Information Table URL
            info_table_url = self.parser.get_information_table_url(filing_url)
            if not info_table_url:
                self.logger.warning("Information Table URL non trovata")
                return False, None

            self.logger.info(f"Trovata Information Table: {info_table_url}")

            # Parse holdings
            holdings = self.parser.parse_information_table(info_table_url)
            if not holdings:
                self.logger.warning("Nessuna holding trovata nel file")
                return False, None

            # Snapshot previous quarter before saving the new one
            portfolio_diff = None
            try:
                prev_accessions = self.storage.get_latest_accessions_for_fund(cik, limit=1)
                prev_accession_number = prev_accessions[0]['accession_number'] if prev_accessions else None
                old_holdings_map = (
                    self.storage.get_holdings_by_accession(prev_accession_number)
                    if prev_accession_number else {}
                )
            except Exception as e:
                self.logger.warning(f"Impossibile recuperare holdings precedenti per diff: {e}")
                old_holdings_map = {}

            # Save to database
            saved_count = self.storage.save_holdings(
                holdings,
                fund_name,
                cik,
                filing_date,
                accession_number,
                filing_url,
                acceptance_datetime=acceptance_datetime or filing_date,
            )

            dashboard_saved_count = 0
            try:
                dashboard_saved_count = self.dashboard_storage.save_holdings(
                    holdings,
                    fund_name,
                    cik,
                    filing_date,
                    accession_number,
                    filing_url,
                    acceptance_datetime=acceptance_datetime or filing_date,
                )
            except Exception as e:
                self.logger.warning(
                    "Salvataggio DuckDB dashboard fallito per %s: %s. "
                    "Le holdings restano salvate in SQLite e verranno riallineate piu tardi.",
                    accession_number,
                    e,
                )

            if saved_count == 0:
                return False, None

            # Compute diff against previous quarter if available
            if old_holdings_map:
                try:
                    new_holdings_map = self.storage.get_holdings_by_accession(accession_number)
                    portfolio_diff = compute_portfolio_diff(old_holdings_map, new_holdings_map)
                    n_new = len(portfolio_diff.get('new_positions', []))
                    n_closed = len(portfolio_diff.get('closed_positions', []))
                    n_changed = len(portfolio_diff.get('increased', [])) + len(portfolio_diff.get('decreased', []))
                    self.logger.info(
                        f"Portfolio diff: +{n_new} nuove, -{n_closed} chiuse, ~{n_changed} variate"
                    )
                except Exception as e:
                    self.logger.warning(f"Impossibile calcolare portfolio diff: {e}")

            self.logger.info(f"Holdings processate con successo per {filer_name}")
            return True, portfolio_diff

        except Exception as e:
            self.logger.error(f"Errore processamento holdings: {e}", exc_info=True)
            return False, None

    def send_daily_summaries(self):
        """Send daily summaries for filtered filings"""
        self.logger.info("📋 Controllo daily summaries...")

        dates_to_send = self.storage.get_daily_summary_dates()

        if not dates_to_send:
            self.logger.info("Nessun daily summary da inviare")
            return

        for date in dates_to_send:
            filings = self.storage.get_filtered_filings_by_date(date)

            if not filings:
                continue

            # Count top filers
            filer_counts = {}
            for filing in filings:
                filer = filing['filer_name']
                filer_counts[filer] = filer_counts.get(filer, 0) + 1

            # Top 5 filers
            top_filers = sorted(filer_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            # Send summary
            if self.notifier.send_daily_summary(date, len(filings), top_filers):
                self.logger.info(f"✓ Daily summary inviato per {date}")
            else:
                self.logger.error(f"✗ Fallito invio daily summary per {date}")


def main():
    """Main entry point"""
    # Load configuration
    try:
        config = Config.from_env()
        config.validate()
    except ValueError as e:
        print(f"ERRORE CONFIGURAZIONE: {e}")
        sys.exit(1)

    # Setup logging
    logger = setup_logging(config.log_file)

    logger.info("=== Avvio 13F Alert System v3.0 (Refactored) ===")
    logger.info(f"Intervallo polling: {config.poll_interval}s ({config.poll_interval/60} minuti)")
    logger.info(
        "Submissions watcher: ultimi %s filing per CIK | delay %.2fs | atom fallback %s",
        config.submissions_recent_limit,
        config.submissions_request_delay_seconds,
        'ON' if config.enable_atom_fallback else 'OFF',
    )
    logger.info(f"Filtro attivo: SI - {len(config.hedge_funds_cik)} hedge funds monitorati (filtro per CIK)")

    # Log first 5 funds
    if config.hedge_funds_cik:
        sample_funds = list(config.hedge_funds_cik.values())[:5]
        logger.info(f"Hedge funds: {', '.join([name.split('(')[0].strip() for name in sample_funds])}...")
    
    # Launch Telegram Viewer (if enabled)
    if config.auto_launch_viewer:
        logger.info("Avvio Telegram Message Viewer...")
        launch_telegram_viewer()
        time.sleep(2)  # Wait for viewer to open
    else:
        logger.info("Auto-avvio viewer disabilitato")

    # Create processor
    processor = FilingProcessor(config)

    # Optional: Export existing holdings to CSV for backward compatibility
    csv_path = Path(config.base_dir) / '13f_holdings_tracker.csv'
    try:
        processor.storage.export_holdings_to_csv(csv_path)
        logger.info(f"Holdings esportati in CSV: {csv_path}")
    except Exception as e:
        logger.warning(f"Impossibile esportare CSV: {e}")

    # Shared state for command handler
    pause_event = threading.Event()       # set = polling paused
    check_now_event = threading.Event()   # set = skip the sleep, run immediately
    last_check_ref: list[datetime | None] = [None]  # last_check_ref[0] = datetime of last feed check

    # Start Telegram command listener (daemon thread)
    cmd_handler = TelegramCommandHandler(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        pause_event=pause_event,
        last_check_ref=last_check_ref,
        check_now_event=check_now_event,
    )
    cmd_handler.start()

    # Main loop
    last_summary_date = datetime.now().date()

    try:
        while True:
            # Honor /stop command: sleep briefly then re-check
            if pause_event.is_set():
                time.sleep(30)
                continue

            current_date = datetime.now().date()

            # Check if new day -> send daily summaries
            if current_date > last_summary_date:
                processor.send_daily_summaries()
                last_summary_date = current_date

                # Cleanup old filings (keep 90 days)
                processor.storage.cleanup_old_filings(days=90)

            # Process feed
            processor.process_filings_cycle()
            last_check_ref[0] = datetime.now()

            # Wait for next cycle (wakes early if /start is sent)
            logger.info(f"Prossimo controllo tra {config.poll_interval/60} minuti")
            check_now_event.wait(timeout=config.poll_interval)
            check_now_event.clear()

    except KeyboardInterrupt:
        logger.info("\nArresto programma richiesto dall'utente")
    except Exception as e:
        logger.critical(f"Errore critico: {e}", exc_info=True)
    finally:
        logger.info("=== Fine programma ===")


if __name__ == '__main__':
    main()
