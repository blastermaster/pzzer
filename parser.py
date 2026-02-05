#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import time
import re
import shutil
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
        self.translation_cache = {}
        
    def translate_param(self, chinese_text):
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
        if not text or not isinstance(text, str):
            return text
        
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
        
        if not has_chinese:
            return text
        
        if text in self.translation_cache:
            return self.translation_cache[text]
        
        try:
            translator = GoogleTranslator(source='zh-CN', target='ru')
            translated = translator.translate(text)
            self.translation_cache[text] = translated
            return translated
        except Exception as e:
            return text
    
    def translate_product_name(self, name):
        if not name or not isinstance(name, str):
            return name
        
        match = re.match(r'^([A-Za-z0-9\s]+)', name)
        
        if match:
            latin_part = match.group(1).strip()
            chinese_part = name[len(match.group(1)):].strip()
            
            if chinese_part:
                translated_chinese = self.translate_chinese_to_russian(chinese_part)
                return f"{latin_part} {translated_chinese}"
            else:
                return latin_part
        else:
            return self.translate_chinese_to_russian(name)
    
    def extract_product_data(self, raw_item, brand_filter=None):
        if 'product' in raw_item and isinstance(raw_item['product'], dict):
            product = raw_item['product']
        else:
            product = raw_item
        
        brand = product.get('brand') or product.get('brandName', '')
        
        if brand_filter and brand.lower() != brand_filter.lower():
            return None
        
        product_id = str(product.get('id') or product.get('productId') or 
                        product.get('spuId') or product.get('sku', ''))
        
        name = product.get('name') or product.get('productName') or product.get('title', '')
        
        condition_raw = product.get('degreeName', '')
        condition = re.sub(r'[^\d.]', '', condition_raw) if condition_raw else ''
        
        price_raw = product.get('originalPrice', 0)
        if price_raw and isinstance(price_raw, (int, float)):
            price_cny = float(price_raw)
            price = str(price_cny)
            price_rub = price_cny * 12 * 1.35
        else:
            price = ''
            price_rub = 0
        
        price_discount_raw = (product.get('price') or product.get('salePrice') or 
                              product.get('currentPrice') or product.get('showPrice', 0))
        
        if price_discount_raw and isinstance(price_discount_raw, (int, float)):
            price_discount_cny = float(price_discount_raw)
            price_discount = str(price_discount_cny)
            price_rub_discount = price_discount_cny * 12 * 1.35
        else:
            price_discount = ''
            price_rub_discount = 0
        
        main_img = product.get('ico') or product.get('image') or product.get('mainImage') or product.get('img')
        if main_img:
            if not main_img.startswith('http'):
                main_img = f"{self.api_config['image_cdn']}/{main_img}"
            main_image = main_img
        else:
            main_image = None
        
        size = product.get('sizeName', '')
        sku = product.get('sku', '')
        
        name_ru = self.translate_product_name(name) if name else ''
        
        return {
            'id': product_id,
            'sku': sku,
            'article': sku,
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
            'city': '',
            'all_images': [main_image] if main_image else [],
            'details': {}
        }
    
    async def get_product_details(self, page, product_id, sku):
        city_code = ''
        article = sku
        
        try:
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
            
            if not api_data:
                return {'details': {}, 'all_images': [], 'city': '', 'article': article}
            
            code = api_data.get('code')
            if code not in [0, '0', 100000, '100000'] or not api_data.get('data'):
                return {'details': {}, 'all_images': [], 'city': '', 'article': article}
            
            product_data = api_data.get('data', {})
            detail = product_data.get('detail', {})
            product_attr = product_data.get('productAttr', {})
            
            store_text_en = detail.get('storeTextEn', '')
            if store_text_en:
                first_word = store_text_en.split()[0] if store_text_en.split() else ''
                if first_word and len(first_word) >= 3:
                    city_code = first_word[:3].upper()
                    article = f"{sku}{city_code}"
            
            details = {}
            
            for item in product_attr:
                if not isinstance(item, dict):
                    continue
                
                param_name = item.get('name', '')
                param_values = item.get('values', [])
                
                if not param_name or not param_values:
                    continue
                
                translated_name = self.translate_param(param_name)
                
                values_list = []
                for val in param_values:
                    if isinstance(val, dict):
                        value_text = val.get('value', '')
                        if value_text:
                            translated_value = self.translate_chinese_to_russian(value_text)
                            values_list.append(translated_value)
                    elif isinstance(val, str):
                        translated_value = self.translate_chinese_to_russian(val)
                        values_list.append(translated_value)
                
                if values_list:
                    combined_value = ' / '.join(values_list)
                    combined_value = re.sub(r'(\d),(\d)', r'\1.\2', combined_value)
                    combined_value = combined_value.replace(',', ' -')
                    details[translated_name] = combined_value
            
            if 'Серийный номер' in details:
                serial = details['Серийный номер']
                if '｜' in serial:
                    parts = serial.split('｜')
                    if len(parts) == 2:
                        details['Серийный номер'] = parts[0].strip()
                        details['Год'] = parts[1].strip()
            
            if 'Вес' in details:
                details['Вес'] = details['Вес'].replace('g', 'г').replace('G', 'г')
            
            all_images = []
            
            if detail:
                image_list = detail.get('imageList', [])
                for img_url in image_list:
                    if isinstance(img_url, str) and img_url:
                        if not img_url.startswith('http'):
                            img_url = f"{self.api_config['image_cdn']}/{img_url}"
                        all_images.append(img_url)
            
            return {
                'details': details,
                'all_images': all_images,
                'city': city_code,
                'article': article
            }
            
        except Exception as e:
            return {'details': {}, 'all_images': [], 'city': '', 'article': sku}
    
    async def parse_task(self, task):
        max_products = self.parsing_config['max_products']
        brand_name = task.get('brand_name', 'Chanel')
        brand_id = task.get('payload', {}).get('brandId', '223')
        
        async with async_playwright() as p:
            print("\n" + "="*60)
            print(f"Задача: {task['name']}")
            print(f"Бренд: {brand_name} (ID: {brand_id})")
            print(f"Максимум товаров: {max_products}")
            print("="*60 + "\n")
            
            print("Запуск браузера...")
            browser = await p.chromium.launch(headless=True)
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
            )
            
            page = await context.new_page()
            
            captured_products = []
            captured_ids = set()
            
            async def capture_response(response):
                url = response.url
                if 'productList' in url:
                    try:
                        data = await response.json()
                        code = str(data.get('code', ''))
                        if code == '100000' and data.get('data') and data['data'].get('list'):
                            for item in data['data']['list']:
                                product = item.get('product') or item
                                if product.get('id'):
                                    brand = product.get('brandName', '').lower()
                                    if brand_name.lower() in brand:
                                        pid = product['id']
                                        if pid not in captured_ids:
                                            captured_ids.add(pid)
                                            captured_products.append(item)
                    except:
                        pass
            
            page.on('response', capture_response)
            
            try:
                print("Открытие: https://mix.goshare2.com/wv/pc/index/")
                await page.goto('https://mix.goshare2.com/wv/pc/index/', wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)
                
                print("Удаление оверлеев...")
                await page.evaluate('''
                    () => {
                        const loginIframe = document.getElementById('zzer-login-iframe');
                        if (loginIframe) loginIframe.remove();
                        
                        document.querySelectorAll('.login-view, .not-login-model').forEach(e => e.remove());
                        document.querySelectorAll('[class*="mask"], [class*="overlay"], [class*="modal"]').forEach(e => e.remove());
                        document.querySelectorAll('.item-wrap').forEach(e => e.remove());
                    }
                ''')
                await asyncio.sleep(1)
                
                print("Переход в раздел 'Купить'...")
                await page.evaluate('''
                    () => {
                        const tabs = document.querySelectorAll('[class*="tab"], [class*="nav"] > *');
                        for (const tab of tabs) {
                            if (tab.textContent.trim() === '购买') {
                                tab.click();
                                return;
                            }
                        }
                    }
                ''')
                await asyncio.sleep(3)
                
                print(f"Выбор бренда {brand_name}...")
                await page.evaluate(f'''
                    () => {{
                        const elements = document.querySelectorAll('*');
                        for (const el of elements) {{
                            const text = (el.textContent || '').trim();
                            if (text.toLowerCase().includes('{brand_name.lower()}') && text.length < 30) {{
                                el.scrollIntoView({{behavior: 'instant', block: 'center'}});
                                el.click();
                                return text;
                            }}
                        }}
                        return null;
                    }}
                ''')
                await asyncio.sleep(5)
                
                print(f"Начальное количество товаров: {len(captured_products)}")
                
                print("\nСкроллинг для загрузки товаров...")
                no_new_count = 0
                for i in range(200):
                    prev = len(captured_products)
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(1.5)
                    
                    if len(captured_products) >= max_products:
                        print(f"\n✓ Достигнут лимит: {max_products} товаров")
                        break
                    
                    if len(captured_products) > prev:
                        no_new_count = 0
                        if len(captured_products) % 100 == 0:
                            print(f"  ✓ Загружено: {len(captured_products)} товаров {brand_name}")
                    else:
                        no_new_count += 1
                        if no_new_count > 15:
                            print(f"\n✓ Все товары загружены")
                            break
                
                print(f"\n{'='*60}")
                print(f"Всего перехвачено: {len(captured_products)} товаров {brand_name}")
                print(f"{'='*60}\n")
                
                if not captured_products:
                    print("⚠️ Не удалось получить товары")
                    return []
                
                products_to_process = captured_products[:max_products]
                total_count = len(products_to_process)
                
                batch_size = self.parsing_config.get('batch_size', 50)
                
                results_dir = Path('products')
                results_dir.mkdir(parents=True, exist_ok=True)
                json_filename_temp = results_dir / f'brand_{brand_id}_temp.json'
                
                processed_products = []
                start_idx = 0
                
                if json_filename_temp.exists():
                    try:
                        with open(json_filename_temp, 'r', encoding='utf-8') as f:
                            temp_data = json.load(f)
                            if isinstance(temp_data, dict) and 'products' in temp_data:
                                processed_products = temp_data['products']
                            else:
                                processed_products = temp_data
                        start_idx = len(processed_products)
                        print(f"✓ Найдено {start_idx} обработанных товаров, продолжаем...")
                    except:
                        processed_products = []
                        start_idx = 0
                
                print(f"\nОбработка {total_count} товаров (батчами по {batch_size})")
                print(f"Прогресс: {start_idx}/{total_count}\n")
                
                for batch_start in range(start_idx, total_count, batch_size):
                    batch_end = min(batch_start + batch_size, total_count)
                    batch_products = products_to_process[batch_start:batch_end]
                    
                    print(f"\n{'─'*60}")
                    print(f"📦 Батч {batch_start // batch_size + 1}: товары {batch_start + 1}-{batch_end}")
                    print(f"{'─'*60}\n")
                    
                    for i, raw_product in enumerate(batch_products):
                        idx = batch_start + i + 1
                        product = self.extract_product_data(raw_product, brand_filter=brand_name)
                        
                        if not product:
                            continue
                        
                        print(f"{idx}. {product['name'][:40]}... ¥{product['price_discount']}")
                        
                        details_data = await self.get_product_details(page, product['id'], product['sku'])
                        
                        product['details'] = details_data.get('details', {})
                        product['city'] = details_data.get('city', '')
                        product['article'] = details_data.get('article', product['sku'])
                        
                        main_img = product['main_image']
                        all_images = []
                        
                        if main_img:
                            all_images.append(main_img)
                        
                        for img_url in details_data.get('all_images', []):
                            if img_url != main_img:
                                all_images.append(img_url)
                        
                        product['all_images'] = all_images
                        processed_products.append(product)
                        
                        await asyncio.sleep(0.2)
                    
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
        results_dir = Path('products')
        results_dir.mkdir(parents=True, exist_ok=True)
        
        brand_id = task.get('payload', {}).get('brandId', 'unknown')
        json_filename_temp = results_dir / f'brand_{brand_id}_temp.json'
        
        data = {
            'updated_at': datetime.now().isoformat(),
            'products': products
        }
        
        with open(json_filename_temp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        total_images = sum(len(p.get('all_images', [])) for p in products)
        print(f"\n  ✓ Сохранено: {len(products)}/{total} товаров ({total_images} изображений)")
    
    def save_results(self, products, task):
        results_dir = Path('products')
        results_dir.mkdir(parents=True, exist_ok=True)
        
        brand_id = task.get('payload', {}).get('brandId', 'unknown')
        
        json_filename = results_dir / f'brand_{brand_id}.json'
        json_filename_temp = results_dir / f'brand_{brand_id}_temp.json'
        updated_at = datetime.now().isoformat()
        
        if json_filename_temp.exists():
            try:
                with open(json_filename_temp, 'r', encoding='utf-8') as f:
                    temp_data = json.load(f)
                    if isinstance(temp_data, dict) and 'updated_at' in temp_data:
                        updated_at = temp_data['updated_at']
            except:
                pass
            
            try:
                shutil.copy2(json_filename_temp, json_filename)
                
                if json_filename.exists() and json_filename.stat().st_size > 0:
                    json_filename_temp.unlink()
                    print(f"\n✓ JSON: {json_filename}")
                else:
                    raise Exception("Файл не был скопирован или пуст")
                    
            except Exception as e:
                print(f"\n✗ Ошибка при сохранении: {e}")
                print(f"   Временный файл сохранен: {json_filename_temp}")
                raise
        else:
            data = {
                'updated_at': updated_at,
                'products': products
            }
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n✓ JSON: {json_filename}")
        
        total_images = sum(len(p.get('all_images', [])) for p in products)
        print(f"\n{'='*60}")
        print("📊 Итого:")
        print(f"   Товаров: {len(products)}")
        print(f"   Изображений (ссылок): {total_images}")
        print(f"   Обновлено: {updated_at}")
        print(f"   Файл: {json_filename}")
        print(f"{'='*60}")
        print("\n✅ Парсинг завершен!")
    
    async def run(self, task_name=None):
        tasks = self.config['tasks']
        
        if task_name:
            tasks_to_run = [t for t in tasks if t['name'].lower() == task_name.lower()]
            if not tasks_to_run:
                print(f"❌ Задача '{task_name}' не найдена")
                print("\nДоступные задачи:")
                for t in tasks:
                    print(f"  - {t['name']}")
                return
        else:
            tasks_to_run = [t for t in tasks if t.get('enabled', False)]
        
        if not tasks_to_run:
            print("❌ Нет активных задач для выполнения")
            print("\nСовет: Установите 'enabled': true в config.json или укажите задачу параметром --task")
            return
        
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
    
    zzer_parser = ZzerParser(args.config)
    
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
    
    await zzer_parser.run(args.task)


if __name__ == "__main__":
    asyncio.run(main())
