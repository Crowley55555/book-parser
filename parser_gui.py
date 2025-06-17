import os
import tkinter as tk
from tkinter import messagebox
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from bs4 import BeautifulSoup
import time
from PIL import Image
import requests
from io import BytesIO
from fpdf import FPDF
import threading
import sys
import subprocess
import logging
from urllib.parse import urlparse
from tkinter import ttk
from bs4.element import Tag
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='parser.log',
    filemode='a'
)

# Константы
SAVE_DIR = 'parsed_pdfs'
MAX_SCROLL_ATTEMPTS = 10
SCROLL_DELAY = 2
BUTTON_CLICK_DELAY = 3
TIMEOUT = 30


class WebPageParser:
    """Парсер веб-страниц с улучшенной поддержкой Flibusta и других сайтов"""

    def __init__(self, status_callback=None):
        self.status_callback = status_callback if status_callback else print
        self.driver = None

        if not os.path.exists(SAVE_DIR):
            os.makedirs(SAVE_DIR)

    def _log_status(self, message):
        logging.info(message)
        print(message)
        self.status_callback(message)

    def _init_driver(self):
        """Инициализация headless-браузера с эмуляцией мобильного устройства"""
        options = FirefoxOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        # User-Agent для Android Chrome (можно заменить на iPhone при необходимости)
        options.set_preference(
            "general.useragent.override",
            "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        )
        self.driver = webdriver.Firefox(options=options)
        self.driver.set_window_size(375, 812)  # Размер экрана iPhone X
        self.driver.set_page_load_timeout(TIMEOUT)

    def _scroll_to_bottom(self):
        """Прокрутка страницы до конца с ожиданием динамической загрузки"""
        self._log_status("Прокрутка страницы...")
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        attempts = 0

        while attempts < MAX_SCROLL_ATTEMPTS:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_DELAY)
            new_height = self.driver.execute_script("return document.body.scrollHeight")

            if new_height == last_height:
                time.sleep(3)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break

            last_height = new_height
            attempts += 1

        self._log_status(f"Прокрутка завершена. Попыток: {attempts}")

    def _expand_all_read_more(self):
        """Прокручивает и нажимает 'Читать далее' пока кнопка есть"""
        self._log_status("Раскрытие всех 'Читать далее'...")
        while True:
            self._scroll_to_bottom()
            try:
                read_more = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(@class, 'more') and contains(text(), 'Читать далее')]"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView();", read_more)
                read_more.click()
                self._log_status("Нажата кнопка 'Читать далее'")
                time.sleep(1)
            except Exception:
                self._log_status("Кнопка 'Читать далее' больше не найдена.")
                break

    def _clean_html(self, soup):
        """Очистка HTML от рекламы и ненужных элементов"""
        # Общие элементы для удаления
        for element in soup(['script', 'style', 'iframe', 'nav', 'footer',
                             'aside', 'form', 'button', 'a', 'header',
                             'svg', 'figure', 'noscript', 'meta', 'link']):
            element.decompose()

        # Специальная очистка для Flibusta
        if 'flibusta.su' in self.driver.current_url:
            for element in soup(['div[id="navigation"]', 'div[class*="booknav"]',
                                 'div[id="comments"]', 'div[class*="ads"]',
                                 'div[id="header"]', 'div[id="menu"]']):
                element.decompose()

        # Удаление элементов с рекламными классами
        bad_classes = ['ad', 'ads', 'banner', 'promo', 'cookie', 'popup',
                       'modal', 'share', 'comment', 'sidebar', 'menu']

        for element in soup.find_all(class_=True):
            if any(bad in ' '.join(element.get('class', [])).lower() for bad in bad_classes):
                element.decompose()

        return soup

    def _find_main_content(self, soup):
        """Поиск основного контента с приоритетом для Flibusta"""
        # Для flibusta ищем по классу (гибко)
        if 'flibusta.su' in self.driver.current_url:
            block = soup.find('div', class_=lambda x: x and 'b_block_center' in x)
            if block:
                return block
            # Логируем все div с похожими классами для отладки
            candidates = soup.find_all('div', class_=lambda x: x and 'block' in x)
            logging.error(f"Кандидаты на основной блок: {[str(c)[:200] for c in candidates]}")
            # Если не найден нужный div, возвращаем body
            if soup.body:
                logging.info("Возвращаю <body> как основной контент для flibusta.su (fallback)")
                return soup.body
        # Стандартный поиск для других сайтов
        for tag in ['article', 'main', 'div[id="content"]', 'div[class*="content"]']:
            container = soup.select_one(tag)
            if container:
                return container

        # Поиск div с наибольшим количеством текста
        divs = soup.find_all('div')
        best_div = None
        max_text_length = 0

        for div in divs:
            text_length = len(div.get_text(strip=True))
            if text_length > max_text_length:
                max_text_length = text_length
                best_div = div

        if not best_div:
            logging.error("Основной контент не найден! HTML: %s", soup.prettify()[:2000])
        return best_div

    def _save_to_pdf(self, elements, url):
        """Создание PDF с сохранением структуры и изображений"""
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        # Настройка шрифта с поддержкой кириллицы
        try:
            font_path = 'LiberationSans-Regular.ttf'
            if os.path.exists(font_path):
                pdf.add_font('LiberationSans', '', font_path, uni=True)
                pdf.set_font('LiberationSans', size=12)
            else:
                pdf.add_font('Arial', '', 'arial.ttf', uni=True)
                pdf.set_font('Arial', size=12)
        except:
            pdf.set_font('Arial', size=12)

        # Обработка элементов
        for el in elements:
            if not isinstance(el, Tag):
                continue
            if el.name == 'img' and el.get('src'):
                try:
                    img_url = el['src']
                    if not img_url.startswith('http'):
                        img_url = requests.compat.urljoin(url, img_url)

                    response = requests.get(img_url, timeout=5)
                    img = Image.open(BytesIO(response.content))

                    # Масштабирование изображения
                    width = pdf.w - 30
                    ratio = width / float(img.size[0])
                    height = float(img.size[1]) * ratio

                    # Временное сохранение изображения
                    img_path = os.path.join(SAVE_DIR, 'temp_img.jpg')
                    img.save(img_path)

                    # Добавление в PDF
                    pdf.image(img_path, x=15, y=pdf.get_y(), w=width, h=height)
                    pdf.ln(h=height + 5)

                    os.remove(img_path)
                except Exception as e:
                    logging.warning(f"Ошибка обработки изображения: {e}")
                    continue
            else:
                text = el.get_text(strip=True)
                if text:
                    try:
                        # Обработка заголовков
                        if el.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                            size = 24 - (int(el.name[1]) * 2)
                            pdf.set_font_size(size)
                            pdf.cell(0, 10, text, ln=1)
                            pdf.set_font_size(12)
                        else:
                            pdf.multi_cell(0, 10, text)
                        pdf.ln(5)
                    except Exception as e:
                        logging.warning(f"Ошибка добавления текста: {e}")
                        continue

        # Генерация имени файла
        domain = urlparse(url).netloc.replace('www.', '').split('.')[0]
        timestamp = int(time.time())
        filename = os.path.join(SAVE_DIR, f"{domain}_{timestamp}.pdf")

        try:
            pdf.output(filename)
            return filename
        except Exception as e:
            logging.error(f"Ошибка сохранения PDF: {e}")
            return None

    def parse_page(self, url):
        """Основной метод парсинга страницы"""
        self._log_status(f"Начало обработки: {url}")

        try:
            # Инициализация драйвера
            self._init_driver()

            # Загрузка страницы
            self._log_status("Загрузка страницы...")
            self.driver.get(url)

            # Специальная обработка для Flibusta
            if 'flibusta.su' in url:
                self._expand_all_read_more()
            else:
                self._scroll_to_bottom()

            # Получение и обработка HTML
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            soup = self._clean_html(soup)
            content = self._find_main_content(soup)

            if not content:
                self._log_status("Не найден основной контент! Проверьте, открыт ли текст книги полностью.")
                # Сохраняем HTML для ручной отладки
                try:
                    with open("debug_page.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    self._log_status("HTML страницы сохранён в debug_page.html для отладки.")
                except Exception as e:
                    self._log_status(f"Ошибка сохранения debug_page.html: {e}")
                return None

            # Защита от None
            elements = content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'img', 'li', 'div[class*="chapter"]']) if content else []

            if not elements:
                self._log_status("Нет элементов для сохранения!")
                return None

            # Сохранение в PDF
            self._log_status("Создание PDF...")
            pdf_path = self._save_to_pdf(elements, url)

            if pdf_path:
                self._log_status(f"Успешно сохранено: {pdf_path}")
                return pdf_path

            self._log_status("Ошибка создания PDF")
            return None

        except Exception as e:
            self._log_status(f"Ошибка: {str(e)}")
            logging.exception("Ошибка парсинга:")
            return None
        finally:
            if self.driver:
                self.driver.quit()


def open_save_dir():
    """Открытие папки с сохраненными PDF"""
    path = os.path.abspath(SAVE_DIR)
    if sys.platform.startswith('win'):
        os.startfile(path)
    elif sys.platform.startswith('darwin'):
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


class ParserGUI:
    """Графический интерфейс для парсера с поддержкой копирования/вставки"""

    def __init__(self, root):
        self.root = root
        self.root.title("Парсер страниц в PDF")
        self.root.geometry("600x250")
        self._setup_ui()

    def _setup_ui(self):
        """Настройка элементов интерфейса с контекстным меню и прогресс-баром"""
        # Цветовая схема
        bg_color = '#23272e'
        fg_color = '#f8f8f2'
        entry_bg = '#2d323b'
        entry_fg = '#f8f8f2'
        btn_bg = '#44475a'
        btn_fg = '#f8f8f2'
        status_fg = '#8be9fd'
        status_bg = '#1e2228'

        self.root.configure(bg=bg_color)

        # Поле для URL
        tk.Label(
            self.root,
            text="Введите URL страницы:",
            bg=bg_color,
            fg=fg_color
        ).pack(pady=5)

        self.url_entry = tk.Entry(
            self.root,
            width=70,
            bg=entry_bg,
            fg=entry_fg,
            insertbackground='#00ffea',
            highlightthickness=1,
            highlightbackground=btn_bg,
            highlightcolor='#00ffea'
        )
        self.url_entry.pack(pady=5)
        self.url_entry.insert(0, "https://...")  # placeholder
        self.url_entry.bind("<FocusIn>", lambda e: self._clear_placeholder())
        self.url_entry.focus_set()  # автофокус

        # Кнопка очистки поля
        clear_btn = tk.Button(
            self.root,
            text="Очистить",
            command=lambda: self.url_entry.delete(0, tk.END),
            bg=btn_bg,
            fg=btn_fg,
            activebackground=btn_fg,
            activeforeground=btn_bg,
            relief=tk.FLAT
        )
        clear_btn.pack(pady=2)

        # Контекстное меню для поля ввода
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Копировать", command=self._copy_text)
        self.context_menu.add_command(label="Вставить", command=self._paste_text)
        self.context_menu.add_command(label="Вырезать", command=self._cut_text)

        # Привязка контекстного меню и горячих клавиш
        self.url_entry.bind("<Button-3>", self._show_context_menu)
        self.url_entry.bind("<Control-v>", lambda e: self._paste_text())
        self.url_entry.bind("<Control-c>", lambda e: self._copy_text())
        self.url_entry.bind("<Control-x>", lambda e: self._cut_text())

        # Статус
        self.status_var = tk.StringVar()
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            fg=status_fg,
            bg=status_bg,
            wraplength=550,
            font=("Arial", 12, "bold"),
            relief=tk.SUNKEN,
            bd=2,
            padx=10,
            pady=5
        )
        self.status_label.pack(pady=5, fill=tk.X, padx=10)

        # Прогресс-бар
        self.progress = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.root,
            variable=self.progress,
            maximum=100,
            length=550,
            mode='indeterminate'
        )
        self.progress_bar.pack(pady=5)

        # Кнопки
        btn_frame = tk.Frame(self.root, bg=bg_color)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame,
            text="Начать парсинг",
            command=self._start_parsing,
            bg=btn_bg,
            fg=btn_fg,
            activebackground=btn_fg,
            activeforeground=btn_bg,
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame,
            text="Открыть папку с PDF",
            command=open_save_dir,
            bg=btn_bg,
            fg=btn_fg,
            activebackground=btn_fg,
            activeforeground=btn_bg,
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=10)

    def _show_context_menu(self, event):
        """Показать контекстное меню"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _copy_text(self):
        """Копировать текст"""
        self.root.clipboard_clear()
        text = self.url_entry.get()
        if text:
            self.root.clipboard_append(text)

    def _paste_text(self):
        """Вставить текст"""
        try:
            text = self.root.clipboard_get()
            if text:
                self.url_entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass

    def _cut_text(self):
        """Вырезать текст"""
        text = self.url_entry.get()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.url_entry.delete(0, tk.END)

    def _update_status(self, message):
        """Обновление статуса"""
        self.status_var.set(message)
        self.root.update_idletasks()

    def _clear_placeholder(self):
        if self.url_entry.get() == "https://...":
            self.url_entry.delete(0, tk.END)

    def _start_parsing(self):
        """Запуск парсинга"""
        url = self.url_entry.get().strip()

        if not url or url == "https://...":
            messagebox.showerror("Ошибка", "Введите URL страницы!")
            return

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        self._update_status("Подготовка...")
        self.progress_bar.start(10)

        threading.Thread(
            target=self._parse_in_thread,
            args=(url,),
            daemon=True
        ).start()

    def _parse_in_thread(self, url):
        """Парсинг в отдельном потоке"""
        parser = WebPageParser(self._update_status)
        result = parser.parse_page(url)

        self.progress_bar.stop()
        self.progress.set(0)

        if result:
            self._update_status(f"Готово! Файл: {result}")
        else:
            self._update_status("Ошибка парсинга. Проверьте URL.")


def main():
    """Запуск приложения"""
    root = tk.Tk()
    app = ParserGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()