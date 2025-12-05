#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import os
import time
import re
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
import argparse
from deep_translator import GoogleTranslator


class ZzerParser:
    def __init__(self, config_file='config.json'):
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.api_config = self.config['api']
        self.device_config = self.config['device']
        self.parsing_config = self.config['parsing']
        
        # Кеш переводов
        self.translation_cache = {}
        
    def build_api_url(self, endpoint_name):
        endpoint = self.api_config['endpoints'][endpoint_name]
        return f"{self.api_config['base_url']}{endpoint}"
    
    def build_payload(self, task_payload):
        # Начинаем с параметров устройства
        payload = dict(self.device_config)
        
        # Добавляем timestamp
        payload['ts'] = str(int(time.time()))
        
        # Добавляем параметры задачи
        payload.update(task_payload)
        
        # Вычисляем sn (подпись)
        payload['sn'] = self.calculate_signature(payload)
        
        return payload
    
    def calculate_signature(self, payload):
        return ""
    
    def translate_param(self, chinese_text):
        """Перевод китайских параметров на русский"""
        translations = {
            '系列': 'Серия',
            '序列号': 'Серийный номер',
            '材质': 'Материал',
            '整体重量': 'Вес',
            '参考尺码': 'Размер',
            '尺寸': 'Размеры',
            '配件': 'Комплект',
            '商品编码': 'Код товара',
            '包身长度': 'Длина',
            '包身高度': 'Высота',
            '包身厚度': 'Ширина',
            '钥匙': 'Ключ',
            '小锁': 'Маленький замок',
            '锁': 'Замок',
            '肩带': 'Ремешок',
            '防尘袋': 'Пылезащитный мешок',
            '盒子': 'Коробка',
            '说明书': 'Инструкция',
            '卡片': 'Карточка',
            '保卡': 'Гарантийная карта'
        }
        return translations.get(chinese_text, chinese_text)
    
    def translate_chinese_to_russian(self, text):
        """Автоматический перевод китайского текста на русский через Google Translate"""
        if not text or not isinstance(text, str):
            return text
        
        # Проверяем есть ли китайские символы
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
        
        if not has_chinese:
            return text
        
        # Проверяем кеш
        if text in self.translation_cache:
            return self.translation_cache[text]
        
        try:
            # Используем GoogleTranslator для перевода
            translator = GoogleTranslator(source='zh-CN', target='ru')
            translated = translator.translate(text)
            
            # Сохраняем в кеш
            self.translation_cache[text] = translated
            
            return translated
        except Exception as e:
            # Если перевод не удался, возвращаем оригинал
            print(f"      Ошибка перевода: {e}")
            return text
    
    def translate_product_name(self, name):
        """Перевод названия товара с сохранением латинских названий серий"""
        if not name or not isinstance(name, str):
            return name
        
        # Извлекаем латинские буквы, цифры и пробелы в начале строки (название серии)
        # Например: "Trendy CC", "Classic Flap", "Boy", "255"
        match = re.match(r'^([A-Za-z0-9\s]+)', name)
        
        if match:
            # Есть латинская часть в начале
            latin_part = match.group(1).strip()
            chinese_part = name[len(match.group(1)):].strip()
            
            if chinese_part:
                # Переводим только китайскую часть
                translated_chinese = self.translate_chinese_to_russian(chinese_part)
                return f"{latin_part} {translated_chinese}"
            else:
                # Только латинская часть
                return latin_part
        else:
            # Нет латинской части, переводим всё
            return self.translate_chinese_to_russian(name)
    
    def extract_product_data(self, raw_item):
        """Извлечение данных из товара"""
        # Проверяем, есть ли вложенный объект product
        if 'product' in raw_item and isinstance(raw_item['product'], dict):
            product = raw_item['product']
        else:
            product = raw_item
        
        # ID товара
        product_id = str(product.get('id') or product.get('productId') or 
                        product.get('spuId') or product.get('sku', ''))
        
        # Название и модель
        name = product.get('name') or product.get('productName') or product.get('title', '')
        
        # Описание
        description = product.get('description') or product.get('desc') or product.get('degreeName', '')
        
        # Оригинальная цена без скидки (основная цена)
        price_raw = product.get('originalPrice', 0)
        if price_raw and isinstance(price_raw, (int, float)):
            price_cny = float(price_raw)
            price = str(price_cny)
            # Конвертация в рубли: юань * 12 * 1.35
            price_rub = price_cny * 12 * 1.35
        else:
            price = ''
            price_rub = 0
        
        # Цена со скидкой (если есть)
        price_discount_raw = (product.get('price') or product.get('salePrice') or 
                              product.get('currentPrice') or product.get('showPrice', 0))
        
        if price_discount_raw and isinstance(price_discount_raw, (int, float)):
            price_discount_cny = float(price_discount_raw)
            price_discount = str(price_discount_cny)
            # Конвертация в рубли: юань * 12 * 1.35
            price_rub_discount = price_discount_cny * 12 * 1.35
        else:
            price_discount = ''
            price_rub_discount = 0
        
        # Основное изображение (главное)
        main_img = product.get('ico') or product.get('image') or product.get('mainImage') or product.get('img')
        if main_img:
            if not main_img.startswith('http'):
                main_img = f"{self.api_config['image_cdn']}/{main_img}"
            main_image = main_img
        else:
            main_image = None
        
        # Дополнительная информация
        brand = product.get('brand') or product.get('brandName', '')
        size = product.get('sizeName', '')
        condition_raw = product.get('degreeName', '')
        # Извлекаем только цифры из condition (например, "9.5新" -> "9.5")
        condition = re.sub(r'[^\d.]', '', condition_raw) if condition_raw else ''
        sku = product.get('sku', '')
        
        # Переводим название на русский (с сохранением латинских названий серий)
        name_ru = self.translate_product_name(name) if name else ''
        
        return {
            'id': product_id,
            'sku': sku,
            'article': '',  # Заполнится при парсинге карточки
            'name': name,
            'name_ru': name_ru,
            'description': f"{condition_raw}. Size: {size}" if size else condition_raw,
            'price': price,
            'price_rub': f"{price_rub:.2f}" if price_rub else '',
            'price_discount': price_discount,
            'price_rub_discount': f"{price_rub_discount:.2f}" if price_rub_discount else '',
            'currency': 'CNY',
            'brand': brand,
            'size': size,
            'condition': condition,
            'main_image': main_image if main_image else '',
            'city': '',  # Заполнится при парсинге карточки
            'all_images': [],  # Заполнится при парсинге карточки
            'details': {}  # Заполнится при парсинге карточки
        }
    
    async def get_product_details(self, page, product_id, sku):
        """Получение детальной информации из карточки товара через API"""
        city_code = ''
        article = sku  # По умолчанию article = sku
        
        try:
            print(f"    Детали товара...")
            
            # Формируем параметры для API запроса
            detail_params = {
                'deviceId': self.device_config['deviceId'],
                'fmt': self.device_config['fmt'],
                'h5Version': self.device_config['h5Version'],
                'id': str(product_id),
                'langType': self.device_config['langType'],
                'mpb': self.device_config['mpb'],
                'mpm': self.device_config['mpm'],
                'mt': self.device_config['mt'],
                'plat': str(self.device_config['plat']),
                'ts': str(int(time.time())),
                'version': self.device_config['version'],
                'sn': ''
            }
            
            api_url = f"{self.api_config['base_url']}/product/api/v1/product/detail"
            
            # Выполняем API запрос через JavaScript в браузере
            api_data = await page.evaluate(f"""
                async () => {{
                    const params = new URLSearchParams({json.dumps(detail_params)});
                    const response = await fetch('{api_url}?' + params.toString(), {{
                        method: 'GET',
                        headers: {{
                            'Accept': 'application/json'
                        }}
                    }});
                    
                    if (response.ok) {{
                        return await response.json();
                    }}
                    return null;
                }}
            """)
            
            # Проверяем успешность ответа (код может быть 0, '0', или вообще отсутствовать при успехе)
            if not api_data:
                print(f"    ✗ Нет данных от API")
                return {
                    'details': {},
                    'all_images': [],
                    'city': '',
                    'article': article  # Возвращаем sku
                }
            
            # Проверяем код успеха (для detail API код = 100000)
            code = api_data.get('code')
            if code not in [0, '0', 100000, '100000'] or not api_data.get('data'):
                print(f"    ✗ Ошибка API: код={code}, msg={api_data.get('msg', 'Unknown')}")
                return {
                    'details': {},
                    'all_images': [],
                    'city': '',
                    'article': article  # Возвращаем sku
                }
            
            # Извлекаем данные из ответа API
            product_data = api_data.get('data', {})
            detail = product_data.get('detail', {})
            product_attr = product_data.get('productAttr', {})
            product_attr_v2 = product_data.get('productAttrV2', {})
            
            # Извлекаем город из storeTextEn (например, "Shanghai ZZER Blackstone | HS3-2")
            store_text_en = detail.get('storeTextEn', '')
            if store_text_en:
                first_word = store_text_en.split()[0] if store_text_en.split() else ''
                if first_word and len(first_word) >= 3:
                    city_code = first_word[:3].upper()
                    article = f"{sku}{city_code}"  # sku + city_code
                    print(f"      ℹ️ Город: {store_text_en} → {city_code}")
            
            
            # Извлекаем параметры из productAttr
            details = {}
            
            for item in product_attr:
                if not isinstance(item, dict):
                    continue
                
                param_name = item.get('name', '')
                param_values = item.get('values', [])
                
                if not param_name or not param_values:
                    continue
                
                # Переводим имя параметра
                translated_name = self.translate_param(param_name)
                
                # Собираем все значения
                values_list = []
                for val in param_values:
                    if isinstance(val, dict):
                        value_text = val.get('value', '')
                        if value_text:
                            # Переводим значение если оно на китайском
                            translated_value = self.translate_chinese_to_russian(value_text)
                            values_list.append(translated_value)
                    elif isinstance(val, str):
                        translated_value = self.translate_chinese_to_russian(val)
                        values_list.append(translated_value)
                
                if values_list:
                    # Объединяем через " / " если несколько значений (чтобы не путать с разделителем CSV)
                    combined_value = ' / '.join(values_list)
                    # Заменяем запятые на точки в десятичных дробях (22,5 -> 22.5)
                    combined_value = re.sub(r'(\d),(\d)', r'\1.\2', combined_value)
                    # Заменяем остальные запятые на " - " (чтобы не ломать CSV)
                    combined_value = combined_value.replace(',', ' -')
                    details[translated_name] = combined_value
            
            # Постобработка деталей
            # 1. Извлекаем год из серийного номера
            if 'Серийный номер' in details:
                serial = details['Серийный номер']
                # Ищем разделитель ｜ и год после него
                if '｜' in serial:
                    parts = serial.split('｜')
                    if len(parts) == 2:
                        details['Серийный номер'] = parts[0].strip()
                        details['Год'] = parts[1].strip()
            
            # 2. Заменяем "g" на "г" в весе
            if 'Вес' in details:
                details['Вес'] = details['Вес'].replace('g', 'г').replace('G', 'г')
            
            # Извлекаем изображения из detail.imageList
            all_images = []
            
            if detail:
                image_list = detail.get('imageList', [])
                for img_url in image_list:
                    if isinstance(img_url, str) and img_url:
                        if not img_url.startswith('http'):
                            img_url = f"{self.api_config['image_cdn']}/{img_url}"
                        all_images.append(img_url)
            
            print(f"    ✓ Параметров: {len(details)}, Изображений: {len(all_images)}")
            
            return {
                'details': details,
                'all_images': all_images,
                'city': city_code,
                'article': article
            }
            
        except Exception as e:
            print(f"    ✗ Ошибка деталей: {e}")
            import traceback
            traceback.print_exc()
            return {
                'details': {},
                'all_images': [],
                'city': '',
                'article': sku  # Возвращаем sku даже при ошибке
            }
    
    async def process_single_product(self, page, raw_product, idx):
        """Обработка одного товара (для параллельного выполнения)"""
        try:
            product = self.extract_product_data(raw_product)
            print(f"{idx}. {product['name'][:50]} - ¥{product['price']} (₽{product['price_rub']})")
            
            # Получаем детали из карточки товара
            details_data = await self.get_product_details(page, product['id'], product['sku'])
            
            # Обновляем продукт
            product['details'] = details_data.get('details', {})
            product['city'] = details_data.get('city', '')
            product['article'] = details_data.get('article', '')
            
            # Объединяем изображения: главное + из карточки
            main_img = product['main_image']
            all_images = []
            
            # Добавляем главное
            if main_img:
                all_images.append(main_img)
            
            # Добавляем остальные из карточки
            for img_url in details_data.get('all_images', []):
                if img_url != main_img:  # Не дублируем главное
                    all_images.append(img_url)
            
            product['all_images'] = all_images
            
            await asyncio.sleep(0.3)  # Небольшая задержка
            return product
            
        except Exception as e:
            print(f"  ✗ Ошибка обработки товара #{idx}: {e}")
            return None
    
    async def parse_task(self, task):
        max_products = self.parsing_config['max_products']
        
        async with async_playwright() as p:
            print("\n" + "="*60)
            print(f"Задача: {task['name']}")
            print("="*60 + "\n")
            
            print("Запуск браузера...")
            browser = await p.chromium.launch(headless=True)
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
            )
            
            page = await context.new_page()
            
            try:
                # Получаем список товаров через API
                print("Открытие: https://mix.goshare2.com/")
                await page.goto("https://mix.goshare2.com/", wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
                
                # Нажимаем кнопку splash
                try:
                    button = await page.query_selector('button, div[class*="button"]')
                    if button:
                        await button.click()
                        print("✓ Splash экран закрыт")
                        await asyncio.sleep(2)
                except:
                    pass
                
                # API запросы с пагинацией
                api_url = self.build_api_url(task['endpoint'])
                
                print(f"\nAPI запрос: {api_url}")
                
                # Собираем товары со всех страниц
                all_products = []
                current_page = 1
                page_size = task['payload'].get('size', 20) or task['payload'].get('pageSize', 20)
                
                while len(all_products) < max_products:
                    # Обновляем номер страницы в payload
                    payload = self.build_payload(task['payload'])
                    payload['page'] = current_page
                    if 'size' in payload:
                        payload['size'] = page_size
                    elif 'pageSize' in payload:
                        payload['pageSize'] = page_size
                    
                    print(f"  Страница {current_page}...", end=' ')
                    
                    api_data = await page.evaluate(f"""
                        async () => {{
                            const response = await fetch('{api_url}', {{
                                method: 'POST',
                                headers: {{
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json'
                                }},
                                body: JSON.stringify({json.dumps(payload)})
                            }});
                            
                            if (response.ok) {{
                                return await response.json();
                            }}
                            return null;
                        }}
                    """)
                    
                    if not api_data or not api_data.get('data'):
                        print("⚠️ Ошибка API")
                        break
                    
                    products_list = api_data.get('data', {}).get('list', [])
                    if not products_list:
                        print("конец списка")
                        break
                    
                    print(f"✓ {len(products_list)} товаров")
                    all_products.extend(products_list)
                    
                    # Если получили меньше чем page_size, значит это последняя страница
                    if len(products_list) < page_size:
                        break
                    
                    current_page += 1
                    await asyncio.sleep(0.5)  # Задержка между запросами страниц
                
                if not all_products:
                    print("⚠️ Не удалось получить товары")
                    return []
                
                print(f"\n✓ Всего получено товаров: {len(all_products)}")
                
                # Ограничиваем количество
                products_to_process = all_products[:max_products]
                total_count = len(products_to_process)
                
                # Размер батча
                batch_size = self.parsing_config.get('batch_size', 50)
                
                # Проверяем, есть ли уже сохраненные результаты
                results_dir = Path('products')
                brand_id = task.get('payload', {}).get('brandId', 'unknown')
                json_filename = results_dir / f'brand_{brand_id}.json'
                
                processed_products = []
                start_idx = 0
                
                if json_filename.exists():
                    try:
                        with open(json_filename, 'r', encoding='utf-8') as f:
                            processed_products = json.load(f)
                        start_idx = len(processed_products)
                        print(f"\n✓ Найдено {start_idx} обработанных товаров, продолжаем с позиции {start_idx + 1}")
                    except:
                        processed_products = []
                        start_idx = 0
                
                print(f"\n{'='*60}")
                print(f"Обработка {total_count} товаров (батчами по {batch_size})")
                print(f"Прогресс: {start_idx}/{total_count}")
                print(f"{'='*60}\n")
                
                # Обрабатываем товары батчами
                for batch_start in range(start_idx, total_count, batch_size):
                    batch_end = min(batch_start + batch_size, total_count)
                    batch_products = products_to_process[batch_start:batch_end]
                    
                    print(f"\n{'─'*60}")
                    print(f"📦 Батч {batch_start // batch_size + 1}: товары {batch_start + 1}-{batch_end} из {total_count}")
                    print(f"{'─'*60}\n")
                    
                    # Обрабатываем товары последовательно (из-за page.goto в каждом товаре)
                    for i, raw_product in enumerate(batch_products):
                        idx = batch_start + i + 1
                        result = await self.process_single_product(page, raw_product, idx)
                        
                        if result and not isinstance(result, Exception):
                            processed_products.append(result)
                    
                    # Промежуточное сохранение после каждого батча
                    self.save_batch(processed_products, task, batch_end, total_count)
                
                return processed_products
                
            except Exception as e:
                print(f"✗ Ошибка: {e}")
                import traceback
                traceback.print_exc()
                return []
            finally:
                await browser.close()
    
    def save_batch(self, products, task, current, total):
        """Промежуточное сохранение батча"""
        results_dir = Path('products')
        results_dir.mkdir(parents=True, exist_ok=True)
        
        brand_id = task.get('payload', {}).get('brandId', 'unknown')
        json_filename = results_dir / f'brand_{brand_id}.json'
        
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        
        total_images = sum(len(p.get('all_images', [])) for p in products)
        print(f"\n  ✓ Сохранено: {len(products)}/{total} товаров ({total_images} изображений)")
    
    def save_results(self, products, task):
        # Создаем папку products
        results_dir = Path('products')
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # Получаем brandId из payload задачи
        brand_id = task.get('payload', {}).get('brandId', 'unknown')
        
        # JSON
        json_filename = results_dir / f'brand_{brand_id}.json'
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        print(f"\n✓ JSON: {json_filename}")
        
        # Статистика
        total_images = sum(len(p.get('all_images', [])) for p in products)
        print(f"\n{'='*60}")
        print("📊 Итого:")
        print(f"   Товаров: {len(products)}")
        print(f"   Изображений (ссылок): {total_images}")
        print(f"   Файл: {json_filename}")
        print(f"{'='*60}")
        print("\n✅ Парсинг завершен!")
    
    async def run(self, task_name=None):
        tasks = self.config['tasks']
        
        # Фильтруем задачи
        if task_name:
            # Ищем задачу по имени
            tasks_to_run = [t for t in tasks if t['name'].lower() == task_name.lower()]
            if not tasks_to_run:
                print(f"❌ Задача '{task_name}' не найдена")
                print("\nДоступные задачи:")
                for t in tasks:
                    print(f"  - {t['name']}")
                return
        else:
            # Берем только enabled задачи
            tasks_to_run = [t for t in tasks if t.get('enabled', False)]
        
        if not tasks_to_run:
            print("❌ Нет активных задач для выполнения")
            print("\nСовет: Установите 'enabled': true в config.json или укажите задачу параметром --task")
            return
        
        # Выполняем задачи
        for task in tasks_to_run:
            products = await self.parse_task(task)
            
            if products:
                self.save_results(products, task)


async def main():
    parser = argparse.ArgumentParser(description='Парсер товаров ZZER')
    parser.add_argument('--config', default='config.json', help='Путь к файлу конфигурации')
    parser.add_argument('--task', help='Название задачи для выполнения (иначе выполняются все enabled)')
    parser.add_argument('--list', action='store_true', help='Показать список доступных задач')
    
    args = parser.parse_args()
    
    # Создаем парсер
    zzer_parser = ZzerParser(args.config)
    
    # Показываем список задач
    if args.list:
        print("\nДоступные задачи в config.json:\n")
        for task in zzer_parser.config['tasks']:
            status = "✓ enabled" if task.get('enabled') else "✗ disabled"
            print(f"  {status}  {task['name']}")
            print(f"          Endpoint: {task['endpoint']}")
            if 'brandId' in task['payload']:
                print(f"          Brand ID: {task['payload']['brandId']}")
            print()
        return
    
    # Запускаем парсер
    await zzer_parser.run(args.task)


if __name__ == "__main__":
    asyncio.run(main())

