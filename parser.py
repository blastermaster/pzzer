#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import os
import csv
import time
import re
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
import aiohttp
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
        
        # Текущая цена со скидкой (уже в юанях)
        price_raw = (product.get('price') or product.get('salePrice') or 
                     product.get('currentPrice') or product.get('showPrice', 0))
        
        if price_raw and isinstance(price_raw, (int, float)):
            price_cny = float(price_raw)
            price = str(price_cny)
            # Конвертация в рубли: юань * 12 * 1.35
            price_rub = price_cny * 12 * 1.35
        else:
            price = str(price_raw) if price_raw else ''
            price_rub = 0
        
        # Оригинальная цена без скидки
        original_price_raw = product.get('originalPrice', 0)
        if original_price_raw and isinstance(original_price_raw, (int, float)):
            original_price_cny = float(original_price_raw)
            original_price = str(original_price_cny)
            # В рублях
            original_price_rub = original_price_cny * 12 * 1.35
        else:
            original_price = ''
            original_price_rub = 0
        
        # Рыночная цена (для справки)
        market_price_raw = product.get('marketPrice', 0)
        if market_price_raw and isinstance(market_price_raw, (int, float)):
            market_price = str(float(market_price_raw))
        else:
            market_price = ''
        
        # Изображения
        images = []
        main_image = None
        
        # Основное изображение (главное)
        main_img = product.get('ico') or product.get('image') or product.get('mainImage') or product.get('img')
        if main_img:
            if not main_img.startswith('http'):
                main_img = f"{self.api_config['image_cdn']}/{main_img}"
            main_image = main_img
            images.append({'url': main_img, 'is_main': True})
        
        # Галерея
        gallery = (product.get('images') or product.get('imageList') or 
                   product.get('gallery') or [])
        
        if isinstance(gallery, list):
            for img in gallery:
                if isinstance(img, str):
                    if not img.startswith('http'):
                        img = f"{self.api_config['image_cdn']}/{img}"
                    # Проверяем, не главное ли это изображение
                    is_main = (img == main_image)
                    if not is_main:  # Не дублируем главное
                        images.append({'url': img, 'is_main': False})
        
        # Дополнительная информация
        brand = product.get('brand') or product.get('brandName', '')
        size = product.get('sizeName', '')
        condition = product.get('degreeName', '')
        sku = product.get('sku', '')
        
        return {
            'id': product_id,
            'sku': sku,
            'name': name,
            'description': f"{condition}. Size: {size}" if size else condition,
            'price': price,
            'price_rub': f"{price_rub:.2f}",
            'original_price': original_price,
            'original_price_rub': f"{original_price_rub:.2f}",
            'market_price': market_price,
            'currency': 'CNY',
            'brand': brand,
            'size': size,
            'condition': condition,
            'images': images,
            'main_image': main_image,
            'details': {},  # Заполнится при парсинге карточки
            'raw_data': raw_item
        }
    
    async def get_product_details(self, page, product_id):
        """Получение детальной информации из карточки товара через API"""
        try:
            print(f"    API детали товара...")
            
            # Формируем параметры для API запроса детали
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
                'sn': ''  # Подпись (пока пустая)
            }
            
            # Формируем URL с параметрами
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
                    'all_images': []
                }
            
            # Проверяем код успеха (для detail API код = 100000)
            code = api_data.get('code')
            if code not in [0, '0', 100000, '100000'] or not api_data.get('data'):
                print(f"    ✗ Ошибка API: код={code}, msg={api_data.get('msg', 'Unknown')}")
                return {
                    'details': {},
                    'all_images': []
                }
            
            # Извлекаем данные из ответа API
            product_data = api_data.get('data', {})
            detail = product_data.get('detail', {})
            product_attr = product_data.get('productAttr', {})
            product_attr_v2 = product_data.get('productAttrV2', {})
            
            
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
                    details[translated_name] = combined_value
            
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
                'all_images': all_images
            }
            
        except Exception as e:
            print(f"    ✗ Ошибка деталей: {e}")
            import traceback
            traceback.print_exc()
            return {
                'details': {},
                'all_images': []
            }
    
    async def download_image(self, session, image_url, product_id, image_index, is_main=False):
        upload_dir = self.parsing_config['upload_dir']
        
        try:
            # Создаем папку для товара: uploads/product_id/
            safe_id = str(product_id).replace('/', '_').replace('\\', '_')
            product_dir = os.path.join(upload_dir, safe_id)
            Path(product_dir).mkdir(parents=True, exist_ok=True)
            
            # Расширение файла
            ext = os.path.splitext(image_url.split('?')[0])[1] or '.jpg'
            if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                ext = '.jpg'
            
            # Формируем имя файла
            if is_main:
                filename = f"main{ext}"
            else:
                filename = f"{image_index}{ext}"
            
            filepath = os.path.join(product_dir, filename)
            
            if os.path.exists(filepath):
                return filepath
            
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    with open(filepath, 'wb') as f:
                        f.write(await response.read())
                    return filepath
            
            return None
            
        except Exception as e:
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
                
                # API запрос
                api_url = self.build_api_url(task['endpoint'])
                payload = self.build_payload(task['payload'])
                
                print(f"\nAPI запрос: {api_url}")
                
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
                    return []
                
                products_list = api_data.get('data', {}).get('list', [])
                if not products_list:
                    print("⚠️ Пустой список товаров")
                    return []
                
                print(f"✓ Получено товаров: {len(products_list)}")
                
                # Ограничиваем количество
                products_to_process = products_list[:max_products]
                
                print(f"\n{'='*60}")
                print(f"Обработка {len(products_to_process)} товаров...")
                print(f"{'='*60}\n")
                
                # Обрабатываем каждый товар
                processed_products = []
                for idx, raw_product in enumerate(products_to_process, 1):
                    product = self.extract_product_data(raw_product)
                    print(f"{idx}. {product['name'][:50]} - ¥{product['price']} (₽{product['price_rub']})")
                    
                    # Получаем детали из карточки товара
                    details_data = await self.get_product_details(page, product['id'])
                    
                    # Обновляем продукт
                    product['details'] = details_data['details']
                    
                    # Объединяем изображения: главное + из карточки
                    main_img = product['main_image']
                    all_images = []
                    
                    # Добавляем главное
                    if main_img:
                        all_images.append({'url': main_img, 'is_main': True})
                    
                    # Добавляем остальные из карточки
                    for img_url in details_data['all_images']:
                        if img_url != main_img:  # Не дублируем главное
                            all_images.append({'url': img_url, 'is_main': False})
                    
                    product['all_images'] = all_images
                    processed_products.append(product)
                    
                    await asyncio.sleep(0.5)  # Задержка между товарами
                
                # Скачивание изображений
                print(f"\n{'='*60}")
                print("Скачивание изображений...")
                print(f"{'='*60}\n")
                
                async with aiohttp.ClientSession() as session:
                    for product in processed_products:
                        print(f"\nТовар: {product['name'][:40]}")
                        downloaded = []
                        
                        tasks = []
                        for idx, img_data in enumerate(product.get('all_images', [])):
                            img_url = img_data['url']
                            is_main = img_data['is_main']
                            tasks.append(self.download_image(session, img_url, product['id'], idx, is_main))
                        
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        downloaded = [r for r in results if r and not isinstance(r, Exception)]
                        
                        product['downloaded_images'] = downloaded
                        print(f"  ✓ Скачано: {len(downloaded)} изображений")
                
                return processed_products
                
            except Exception as e:
                print(f"✗ Ошибка: {e}")
                import traceback
                traceback.print_exc()
                return []
            finally:
                await browser.close()
    
    def save_results(self, products, task_name):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Безопасное имя файла из названия задачи
        safe_name = "".join(c for c in task_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_name = safe_name.replace(' ', '_').lower()
        
        # JSON
        json_filename = f'products_{safe_name}_{timestamp}.json'
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        print(f"\n✓ JSON: {json_filename}")
        
        # CSV для 1С
        csv_filename = f'products_1c_{safe_name}_{timestamp}.csv'
        with open(csv_filename, 'w', encoding='utf-8-sig', newline='') as csvfile:
            # Получаем все уникальные параметры из details
            all_detail_keys = set()
            for product in products:
                all_detail_keys.update(product.get('details', {}).keys())
            
            # Базовые поля
            fieldnames = [
                'Код', 
                'Артикул', 
                'Наименование', 
                'Цена_CNY', 
                'Цена_RUB', 
                'ЦенаБезСкидки_CNY',
                'ЦенаБезСкидки_RUB',
                'ЦенаРыночная_CNY', 
                'Валюта', 
                'Бренд', 
                'Состояние'
            ]
            
            # Фиксированный порядок для часто встречающихся параметров
            preferred_order = [
                'Серия',
                'Серийный номер', 
                'Материал',
                'Вес',
                'Размеры',
                'Комплект'
            ]
            
            # Добавляем поля деталей в правильном порядке
            detail_keys_sorted = []
            
            # Сначала добавляем в предпочтительном порядке
            for key in preferred_order:
                if key in all_detail_keys:
                    detail_keys_sorted.append(key)
            
            # Потом добавляем остальные (в алфавитном порядке)
            remaining_keys = sorted(all_detail_keys - set(preferred_order))
            detail_keys_sorted.extend(remaining_keys)
            
            fieldnames.extend(detail_keys_sorted)
            
            # Добавляем поля для картинок (в конце!)
            for i in range(1, 11):
                fieldnames.append(f'Картинка{i}')
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';', 
                                   quoting=csv.QUOTE_MINIMAL, quotechar='"')
            writer.writeheader()
            
            for product in products:
                images = product.get('downloaded_images', [])
                image_dict = {f'Картинка{i+1}': images[i] if i < len(images) else '' for i in range(10)}
                
                # Формируем строку с деталями
                details_dict = {}
                for key in detail_keys_sorted:
                    details_dict[key] = product.get('details', {}).get(key, '')
                
                # Формируем строку для записи
                row_data = {
                    'Код': product['id'],
                    'Артикул': product.get('sku', ''),
                    'Наименование': product['name'],
                    'Цена_CNY': product['price'],
                    'Цена_RUB': product.get('price_rub', ''),
                    'ЦенаБезСкидки_CNY': product.get('original_price', ''),
                    'ЦенаБезСкидки_RUB': product.get('original_price_rub', ''),
                    'ЦенаРыночная_CNY': product.get('market_price', ''),
                    'Валюта': product['currency'],
                    'Бренд': product.get('brand', ''),
                    'Состояние': product.get('condition', '')
                }
                
                # Добавляем детали
                row_data.update(details_dict)
                
                # Добавляем картинки
                row_data.update(image_dict)
                
                writer.writerow(row_data)
        
        print(f"✓ CSV для 1С: {csv_filename}")
        
        # Статистика
        total_images = sum(len(p.get('downloaded_images', [])) for p in products)
        print(f"\n{'='*60}")
        print("📊 Итого:")
        print(f"   Товаров: {len(products)}")
        print(f"   Изображений: {total_images}")
        print(f"   Папка: {self.parsing_config['upload_dir']}/")
        print(f"   CSV для 1С: {csv_filename}")
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
                self.save_results(products, task['name'])


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

