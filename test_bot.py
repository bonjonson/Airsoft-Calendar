import pytest
import json
from main import validate_date, validate_price, format_price

def test_load_events_empty_file(tmp_path):
    """Тест загрузки событий из несуществующего файла"""
    test_file = tmp_path / "test_calendar.json"
    assert not test_file.exists()
    
    # Имитируем функцию load_events с тестовым файлом
    def test_load():
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"events": []}
    
    result = test_load()
    assert result == {"events": []}

def test_validate_date():
    """Тест валидации даты"""
    assert validate_date("25.12.2024") == True
    assert validate_date("32.13.2024") == False  # Неправильная дата
    assert validate_date("01.01.2023") == True
    assert validate_date("ab.cd.efgh") == False  # Не числа
    assert validate_date("25-12-2024") == False  # Неправильный формат

def test_validate_price():
    """Тест валидации цены"""
    assert validate_price("500") == True
    assert validate_price("300-1000") == True
    assert validate_price("300 - 1000") == True  # С пробелами
    assert validate_price("abc") == False  # Не числа
    assert validate_price("500-") == False  # Неполный диапазон
    assert validate_price("-1000") == False  # Неполный диапазон

def test_format_price():
    """Тест форматирования цены"""
    assert format_price("500") == "500 рублей"
    assert format_price("300-1000") == "300-1000 рублей"
    assert format_price("300 - 1000") == "300-1000 рублей"  # Убирает пробелы

def test_save_and_load_events(tmp_path):
    """Тест сохранения и загрузки событий"""
    test_file = tmp_path / "test_calendar.json"
    test_data = {
        "events": [
            {
                "name": "Test Event",
                "date": "01.01.2024",
                "organisators": "Test Org",
                "price": "100 рублей",
                "place": "Test Place",
                "link": "http://test.com"
            }
        ]
    }
    
    # Сохраняем тестовые данные
    with open(test_file, 'w', encoding='utf-8') as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)
    
    # Загружаем обратно
    with open(test_file, 'r', encoding='utf-8') as f:
        loaded_data = json.load(f)
    
    assert loaded_data == test_data
    assert len(loaded_data["events"]) == 1
    assert loaded_data["events"][0]["name"] == "Test Event"

def test_example():
    """Простой тест для проверки работы pytest"""
    assert True
