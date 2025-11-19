#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import os
import csv
import time
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
import aiohttp
import argparse


class ZzerParser:
    def __init__(self, config_file='config.json'):
        with open(config_file, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.api_config = self.config['api']
        self.device_config = self.config['device']
        self.parsing_config = self.config['parsing']
        
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
        
        # Цена (в центах, делим на 100)
        price_raw = (product.get('price') or product.get('salePrice') or 
                     product.get('currentPrice') or product.get('showPrice', 0))
        
        if price_raw and isinstance(price_raw, (int, float)):
            price = str(float(price_raw) / 100)
        else:
            price = str(price_raw) if price_raw else ''
        
        # Рыночная цена
        market_price_raw = product.get('marketPrice', 0)
        if market_price_raw and isinstance(market_price_raw, (int, float)):
            market_price = str(float(market_price_raw) / 100)
        else:
            market_price = ''
        
        # Изображения
        images = []
        
        # Основное изображение
        main_img = product.get('ico') or product.get('image') or product.get('mainImage') or product.get('img')
        if main_img:
            if not main_img.startswith('http'):
                main_img = f"{self.api_config['image_cdn']}/{main_img}"
            images.append(main_img)
        
        # Галерея
        gallery = (product.get('images') or product.get('imageList') or 
                   product.get('gallery') or [])
        
        if isinstance(gallery, list):
            for img in gallery:
                if isinstance(img, str):
                    if not img.startswith('http'):
                        img = f"{self.api_config['image_cdn']}/{img}"
                    images.append(img)
        
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
            'market_price': market_price,
            'currency': 'CNY',
            'brand': brand,
            'size': size,
            'condition': condition,
            'images': images,
            'raw_data': raw_item
        }
    
    async def download_image(self, session, image_url, product_id, image_index):
        upload_dir = self.parsing_config['upload_dir']
        
        try:
            Path(upload_dir).mkdir(parents=True, exist_ok=True)
            
            # Расширение файла
            ext = os.path.splitext(image_url.split('?')[0])[1] or '.jpg'
            if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                ext = '.jpg'
            
            # Чистим product_id от спецсимволов
            safe_id = str(product_id).replace('/', '_').replace('\\', '_')
            filename = f"{safe_id}_{image_index}{ext}"
            filepath = os.path.join(upload_dir, filename)
            
            if os.path.exists(filepath):
                print(f"  ✓ Уже есть: {filename}")
                return filepath
            
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    with open(filepath, 'wb') as f:
                        f.write(await response.read())
                    print(f"  ✓ Скачано: {filename}")
                    return filepath
            
            return None
            
        except Exception as e:
            print(f"  ✗ Ошибка: {e}")
            return None
    
    async def fetch_products_via_browser(self, task):
        print(f"\n{'='*60}")
        print(f"Задача: {task['name']}")
        print(f"{'='*60}\n")
        
        async with async_playwright() as p:
            print("Запуск браузера...")
            browser = await p.chromium.launch(headless=True)
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
            )
            
            page = await context.new_page()
            
            try:
                # Открываем главную страницу
                print("Открытие: https://mix.goshare2.com/")
                await page.goto("https://mix.goshare2.com/", wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
                
                # Нажимаем кнопку если есть splash
                try:
                    button = await page.query_selector('button, div[class*="button"]')
                    if button:
                        await button.click()
                        print("✓ Splash экран закрыт")
                        await asyncio.sleep(2)
                except:
                    pass
                
                # Формируем API запрос
                api_url = self.build_api_url(task['endpoint'])
                payload = self.build_payload(task['payload'])
                
                print(f"\nAPI запрос: {api_url}")
                print(f"Параметры: {json.dumps(payload, ensure_ascii=False, indent=2)[:200]}...")
                
                # Выполняем API запрос через JavaScript
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
                
                await browser.close()
                
                if api_data and api_data.get('data'):
                    products_list = api_data.get('data', {}).get('list', [])
                    if products_list:
                        print(f"✓ Получено товаров: {len(products_list)}")
                        return products_list
                    else:
                        print("⚠️ Пустой список товаров")
                        return []
                else:
                    print(f"⚠️ Ошибка API: {api_data.get('msg', 'Неизвестная ошибка')}")
                    return []
                
            except Exception as e:
                print(f"✗ Ошибка: {e}")
                import traceback
                traceback.print_exc()
                return []
            finally:
                await browser.close()
    
    async def parse_task(self, task):
        max_products = self.parsing_config['max_products']
        
        # Получаем товары
        products_list = await self.fetch_products_via_browser(task)
        
        if not products_list:
            print("\n❌ Товары не получены")
            return []
        
        # Ограничиваем количество
        products_to_process = products_list[:max_products]
        
        print(f"\n{'='*60}")
        print(f"Обработка {len(products_to_process)} товаров...")
        print(f"{'='*60}\n")
        
        processed_products = []
        for idx, raw_product in enumerate(products_to_process, 1):
            product = self.extract_product_data(raw_product)
            processed_products.append(product)
            print(f"{idx}. {product['name'][:50]} - ¥{product['price']}")
        
        # Скачивание изображений
        print(f"\n{'='*60}")
        print("Скачивание изображений...")
        print(f"{'='*60}\n")
        
        async with aiohttp.ClientSession() as session:
            for product in processed_products:
                if not product['images']:
                    continue
                
                print(f"\nТовар: {product['name'][:40]}")
                downloaded = []
                
                tasks = []
                for idx, img_url in enumerate(product['images'][:5]):
                    tasks.append(self.download_image(session, img_url, product['id'], idx))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                downloaded = [r for r in results if r and not isinstance(r, Exception)]
                
                product['downloaded_images'] = downloaded
        
        return processed_products
    
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
            fieldnames = [
                'Код', 'Артикул', 'Наименование', 'Описание', 
                'Цена', 'ЦенаРыночная', 'Валюта', 'Бренд', 'Размер', 'Состояние',
                'Картинка1', 'Картинка2', 'Картинка3', 'Картинка4', 'Картинка5'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            
            for product in products:
                images = product.get('downloaded_images', [])
                image_dict = {f'Картинка{i+1}': images[i] if i < len(images) else '' for i in range(5)}
                
                writer.writerow({
                    'Код': product['id'],
                    'Артикул': product.get('sku', ''),
                    'Наименование': product['name'],
                    'Описание': product.get('description', ''),
                    'Цена': product['price'],
                    'ЦенаРыночная': product.get('market_price', ''),
                    'Валюта': product['currency'],
                    'Бренд': product.get('brand', ''),
                    'Размер': product.get('size', ''),
                    'Состояние': product.get('condition', ''),
                    **image_dict
                })
        
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

