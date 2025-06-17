# book-parser

## Описание

Простой парсер сайтов с GUI на tkinter. Позволяет по ссылке получить текст и изображения с сайта, сохранить их в PDF (с поддержкой кириллицы) в отдельной папке. Есть кнопка для открытия папки с PDF.

## Установка

1. Клонируйте репозиторий или скачайте архив с кодом.
2. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```
3. Скачайте [geckodriver](https://github.com/mozilla/geckodriver/releases) и поместите его в PATH или рядом с parser_gui.py. Geckodriver должен соответствовать вашей версии Firefox.
4. Скачайте файл шрифта `arial.ttf` (или другой unicode-шрифт, например, [LiberationSans-Regular.ttf](https://github.com/liberationfonts/liberation-fonts/files/6756756/LiberationSans-Regular.ttf)) и положите его в папку с parser_gui.py.

## Запуск

```bash
python parser_gui.py
```

## Использование
- Введите ссылку на сайт.
- Нажмите "Парсинг" — будет создан PDF с текстом и картинками в папке `parsed_pdfs`.
- Кнопка "Открыть папку с PDF" откроет папку с результатами.

## Важно
- Для корректной работы с кириллицей необходим файл шрифта `arial.ttf` или другой unicode-шрифт.
- Для работы selenium необходим geckodriver, совместимый с вашей версией Firefox.

## Пример структуры проекта
```
book-parser/
├── parser_gui.py
├── requirements.txt
├── README.md
├── arial.ttf
└── parsed_pdfs/
```

