# -*- coding: utf-8 -*-
from flask import Flask, render_template, request
from datetime import datetime, timedelta, date 
import gspread # type: ignore
import traceback 
import re
from collections import defaultdict

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ ---
GOOGLE_SHEET_ID = '1jBuLeH6o7HCmPswOScorR6nM1X7B4LrXooK4VmjpLAI' 
GOOGLE_SHEET_TAB_NAME = 'RATEEXPIDR' 
CREDENTIALS_FILE = 'credentials.json' 

# --- Ключи заголовков для консистентности ---
HEADER_KEY_HOTELN = 'HOTELN'
HEADER_KEY_CATEGORY = 'CATEGORY'
HEADER_KEY_REGION = 'REGION'
HEADER_KEY_START_PERIOD = 'START_PERIOD'
HEADER_KEY_END_PERIOD = 'END_PERIOD'     
HEADER_KEY_ROOM_IDR = 'ROOM_IDR'
HEADER_KEY_FB_ADT = 'FB_ADT'; HEADER_KEY_FB_CHLD = 'FB_CHLD'   
HEADER_KEY_HB_ADT = 'HB_ADT'; HEADER_KEY_HB_CHLD = 'HB_CHLD'   
HEADER_KEY_AI_ADT = 'ALL_INCL_ADT'; HEADER_KEY_AI_CHLD = 'ALL_INCL_CHLD'
HEADER_KEY_EBED_ADT = 'EBED_ADT'; HEADER_KEY_EBED_CHLD = 'EBED_CHLD'
HEADER_KEY_NY_DINNER_ADT = 'NY_DINNER_ADT'; HEADER_KEY_NY_DINNER_CHLD = 'NY_DINNER_CHLD'
HEADER_KEY_REMNYD = 'REMNYD'
HEADER_KEY_BFST_CHLD = 'BFST_CHLD'
HEADER_KEY_SPOEXP = 'SPOEXP'; HEADER_KEY_REMSPO = 'REMSPO'; HEADER_KEY_EBIRD = 'EBIRD'
HEADER_KEY_REM1 = 'REM1' # <-- ДОБАВЛЕНО
HEADER_KEY_REM2 = 'REM2'
HEADER_KEY_CXL = 'CXL'   # <-- ДОБАВЛЕНО


# --- Вспомогательные функции ---
def normalize_string(s: str) -> str:
    if not isinstance(s, str): s = str(s)
    s = re.sub(r'\s+', ' ', s) 
    return s.strip().lower()

def clean_price_string(price_str: str) -> int:
    if not price_str: return 0
    try:
        price_str = str(price_str).replace(' ', '').replace('\u00A0', '')
        cleaned_str = price_str.replace(',', '.')
        return int(float(cleaned_str))
    except (ValueError, TypeError): return 0

def get_structured_hotel_data() -> dict:
    try:
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
        worksheet = spreadsheet.worksheet(GOOGLE_SHEET_TAB_NAME)
        all_records = worksheet.get_all_records()
        hotel_data = defaultdict(lambda: defaultdict(set))
        for record in all_records:
            region = str(record.get(HEADER_KEY_REGION, '')).strip()
            hotel = str(record.get(HEADER_KEY_HOTELN, '')).strip()
            category = str(record.get(HEADER_KEY_CATEGORY, '')).strip()
            if region and hotel and category:
                hotel_data[region][hotel].add(category)
        final_data = { region: { hotel: sorted(list(categories)) for hotel, categories in hotels.items() } for region, hotels in hotel_data.items() }
        return final_data
    except Exception as e:
        print(f"Ошибка при получении структурированных данных из Google Sheets: {e}")
        return {}

def parse_additional_options(options_str: str) -> dict:
    parsed_data = { 'wants_fb': False, 'wants_hb': False, 'wants_ai': False, 'extra_bed_child_count': 0, 'extra_bed_adult_count': 0, 'wants_sharing_bed': False }
    if not options_str or not options_str.strip() or options_str.strip() == '-': return parsed_data
    options_lower = options_str.lower()
    if any(keyword in options_lower for keyword in ["fb", "full board", "полный пансион"]): parsed_data['wants_fb'] = True
    elif any(keyword in options_lower for keyword in ["hb", "half board", "полупансион"]): parsed_data['wants_hb'] = True
    elif any(keyword in options_lower for keyword in ["ai", "all inclusive", "все включено"]): parsed_data['wants_ai'] = True
    extra_bed_keywords = ["extra bed", "доп кровать", "e.bed"]; child_keywords = ["child", "ребенка"]
    if any(keyword in options_lower for keyword in extra_bed_keywords):
        if any(keyword in options_lower for keyword in child_keywords): parsed_data['extra_bed_child_count'] = 1
        else: parsed_data['extra_bed_adult_count'] = 1
    if "sharing bed" in options_lower: parsed_data['wants_sharing_bed'] = True
    print(f"DEBUG_WEB_PARSE: Распарсенные опции: {parsed_data}")
    return parsed_data

# --- Основная функция расчета ---
def calculate_price_for_web(user_data_dict: dict) -> list:
    print(f"WEB_CALC: Начинаем расчет. Входные данные: {user_data_dict}")
    calculation_output_lines = [] 
    try: 
        checkin_str = user_data_dict.get('checkin_date'); checkout_str = user_data_dict.get('checkout_date')
        hotel_name_input = user_data_dict.get('hotel', ''); category_input = user_data_dict.get('category', '') 
        hotel_name_user = normalize_string(hotel_name_input); category_user = normalize_string(category_input)
        adults_count = int(user_data_dict.get('adults_count', 0)); children_count_val_calc = int(user_data_dict.get('children_count', 0))
        additional_options_str = user_data_dict.get('additional_options', '')
        try: usd_rate = float(user_data_dict.get('usd_rate', '0').replace(',', '.'))
        except (ValueError, TypeError): usd_rate = 0.0

        if not all([checkin_str, checkout_str, hotel_name_user, category_user, adults_count > 0]):
            calculation_output_lines.append("<b>Ошибка:</b> Не все данные для расчета были предоставлены или количество взрослых 0.")
            return calculation_output_lines

        checkin_date_obj = datetime.strptime(checkin_str, "%d.%m.%Y").date(); checkout_date_obj = datetime.strptime(checkout_str, "%d.%m.%Y").date()
        num_nights = (checkout_date_obj - checkin_date_obj).days
        if num_nights <= 0:
            calculation_output_lines.append("<b>Ошибка:</b> Дата выезда должна быть позже даты заезда.")
            return calculation_output_lines
        
        parsed_user_options = parse_additional_options(additional_options_str) 
        gc = gspread.service_account(filename=CREDENTIALS_FILE); spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
        worksheet = spreadsheet.worksheet(GOOGLE_SHEET_TAB_NAME); all_records = worksheet.get_all_records()
        
        total_room_cost_idr = 0; total_surcharges_idr = 0
        calculation_details_temp = [
            f"<b>Детализация расчета для отеля '{hotel_name_input}', категория '{category_input}':</b>",
            f"Период: {checkin_str} - {checkout_str} ({num_nights} ночей).",
            f"Гости: Взрослых - {adults_count}, Детей - {children_count_val_calc}.\n"
        ]
        surcharge_details_parts_temp = []; found_rates_for_all_nights = True
        
        # --- ИЗМЕНЕНИЕ: Добавлены новые хранилища для ремарок ---
        policy_remarks_set = set(); special_offer_remarks_set = set()
        general_remarks_set = set(); cancellation_policy_set = set()
        
        today = date.today()
        
        for i in range(num_nights):
            current_night_date_obj = checkin_date_obj + timedelta(days=i) 
            valid_rates_for_night = [] 
            for record in all_records:
                sheet_hotel = normalize_string(record.get(HEADER_KEY_HOTELN, ''))
                sheet_category = normalize_string(record.get(HEADER_KEY_CATEGORY, ''))
                if hotel_name_user in sheet_hotel and category_user in sheet_category:
                    period_start_str = str(record.get(HEADER_KEY_START_PERIOD, '')); period_end_str = str(record.get(HEADER_KEY_END_PERIOD, ''))
                    if not period_start_str or not period_end_str : continue 
                    try: 
                        period_start_date_obj = datetime.strptime(period_start_str, "%d.%m.%Y").date()
                        period_end_date_obj = datetime.strptime(period_end_str, "%d.%m.%Y").date()
                        if period_start_date_obj <= current_night_date_obj <= period_end_date_obj:
                            price = clean_price_string(str(record.get(HEADER_KEY_ROOM_IDR, '')))
                            if price <= 0: continue 
                            is_valid_offer = False; offer_remark = "Стандартный тариф"
                            spoexp_str = str(record.get(HEADER_KEY_SPOEXP, '')).strip(); ebird_str = str(record.get(HEADER_KEY_EBIRD, '')).strip()
                            if spoexp_str:
                                try:
                                    spoexp_date = datetime.strptime(spoexp_str, "%d.%m.%Y").date()
                                    if today <= spoexp_date: is_valid_offer = True; offer_remark = str(record.get(HEADER_KEY_REMSPO, '')).strip()
                                except (ValueError, TypeError): is_valid_offer = False 
                            elif ebird_str: 
                                try:
                                    ebird_days = int(ebird_str); days_until_checkin = (checkin_date_obj - today).days
                                    if days_until_checkin >= ebird_days: is_valid_offer = True; offer_remark = f"Применяется EARLY BIRD - {ebird_days} дней до заезда"
                                except ValueError: is_valid_offer = False
                            else: is_valid_offer = True
                            if is_valid_offer: valid_rates_for_night.append({'price': price, 'record': record, 'remark': offer_remark})
                    except (ValueError, TypeError): pass
            rate_for_current_night = None; applicable_record_for_surcharges = None
            if valid_rates_for_night:
                best_rate_info = min(valid_rates_for_night, key=lambda x: x['price'])
                rate_for_current_night = best_rate_info['price']; applicable_record_for_surcharges = best_rate_info['record']
                if best_rate_info['remark'] and best_rate_info['remark'] != "Стандартный тариф": special_offer_remarks_set.add(best_rate_info['remark'])
                print(f"    --> ВЫБРАН ТАРИФ на {current_night_date_obj.strftime('%d.%m.%Y')}: {rate_for_current_night} IDR (Тип: '{best_rate_info['remark']}')")
            if rate_for_current_night is not None:
                total_room_cost_idr += rate_for_current_night
                calculation_details_temp.append(f"Ночь {i+1} ({current_night_date_obj.strftime('%d.%m.%Y')}): {rate_for_current_night:,.0f} IDR (номер)")
                if applicable_record_for_surcharges:
                    surcharges_for_current_night_this_night = 0; cost = 0 
                    if parsed_user_options['wants_fb']: cost = (clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_FB_ADT, '0'))*adults_count + clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_FB_CHLD, '0'))*children_count_val_calc)
                    elif parsed_user_options['wants_hb']: cost = (clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_HB_ADT, '0'))*adults_count + clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_HB_CHLD, '0'))*children_count_val_calc)
                    elif parsed_user_options['wants_ai']: cost = (clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_AI_ADT, '0'))*adults_count + clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_AI_CHLD, '0'))*children_count_val_calc)
                    if cost > 0: surcharge_details_parts_temp.append(f"  Доплата за питание (ночь {i+1}): {cost:,.0f} IDR")
                    surcharges_for_current_night_this_night += cost
                    if parsed_user_options['extra_bed_adult_count'] > 0:
                        cost_eb_adt = clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_EBED_ADT, '0'))*parsed_user_options['extra_bed_adult_count']
                        if cost_eb_adt > 0: surcharges_for_current_night_this_night += cost_eb_adt; surcharge_details_parts_temp.append(f"  Доп. кровать (взр) (ночь {i+1}): {cost_eb_adt:,.0f} IDR")
                    if parsed_user_options['extra_bed_child_count'] > 0:
                        cost_eb_chld = clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_EBED_CHLD, '0'))*parsed_user_options['extra_bed_child_count']
                        if cost_eb_chld > 0: surcharges_for_current_night_this_night += cost_eb_chld; surcharge_details_parts_temp.append(f"  Доп. кровать (реб) (ночь {i+1}): {cost_eb_chld:,.0f} IDR")
                    if parsed_user_options['wants_sharing_bed'] and children_count_val_calc > 0:
                        cost_bfst_chld = clean_price_string(applicable_record_for_surcharges.get(HEADER_KEY_BFST_CHLD, '0'))*children_count_val_calc
                        if cost_bfst_chld > 0: surcharges_for_current_night_this_night += cost_bfst_chld; surcharge_details_parts_temp.append(f"  Завтрак для ребенка (sharing bed) (ночь {i+1}): {cost_bfst_chld:,.0f} IDR")
                total_surcharges_idr += surcharges_for_current_night_this_night
                if children_count_val_calc > 0 and applicable_record_for_surcharges:
                    rem2_text = str(applicable_record_for_surcharges.get(HEADER_KEY_REM2, '')).strip()
                    if rem2_text: policy_remarks_set.add(rem2_text)
                # --- ИЗМЕНЕНИЕ: Собираем ремарки REM1 и CXL ---
                if applicable_record_for_surcharges:
                    rem1_text = str(applicable_record_for_surcharges.get(HEADER_KEY_REM1, '')).strip()
                    if rem1_text: general_remarks_set.add(rem1_text)
                    cxl_text = str(applicable_record_for_surcharges.get(HEADER_KEY_CXL, '')).strip()
                    if cxl_text: cancellation_policy_set.add(cxl_text)
            else: calculation_details_temp.append(f"Ночь {i+1} ({current_night_date_obj.strftime('%d.%m.%Y')}): <b>ТАРИФ НЕ НАЙДЕН!</b>"); found_rates_for_all_nights = False
        try:
            new_year_eve_date = date(checkin_date_obj.year, 12, 31)
            if checkin_date_obj <= new_year_eve_date < checkout_date_obj:
                record_for_ny_dinner_lookup = None
                for rec_ny_check in all_records:
                    if normalize_string(rec_ny_check.get(HEADER_KEY_HOTELN, '')) == hotel_name_user and normalize_string(rec_ny_check.get(HEADER_KEY_CATEGORY, '')) == category_user:
                        ny_period_start_str = str(rec_ny_check.get(HEADER_KEY_START_PERIOD, '')); ny_period_end_str = str(rec_ny_check.get(HEADER_KEY_END_PERIOD, ''))
                        if not ny_period_start_str or not ny_period_end_str: continue
                        try:
                            ny_period_start = datetime.strptime(ny_period_start_str, "%d.%m.%Y").date(); ny_period_end = datetime.strptime(ny_period_end_str, "%d.%m.%Y").date()
                            if ny_period_start <= new_year_eve_date <= ny_period_end: record_for_ny_dinner_lookup = rec_ny_check; break 
                        except ValueError: continue
                if record_for_ny_dinner_lookup:
                    ny_adt_cost_str = record_for_ny_dinner_lookup.get(HEADER_KEY_NY_DINNER_ADT, ''); ny_chld_cost_str = record_for_ny_dinner_lookup.get(HEADER_KEY_NY_DINNER_CHLD, '')
                    if ny_adt_cost_str or ny_chld_cost_str: 
                        ny_adt_cost = clean_price_string(ny_adt_cost_str); ny_chld_cost = clean_price_string(ny_chld_cost_str)
                        ny_dinner_total_cost = (ny_adt_cost * adults_count) + (ny_chld_cost * children_count_val_calc)
                        if ny_dinner_total_cost > 0:
                            total_surcharges_idr += ny_dinner_total_cost; surcharge_details_parts_temp.append(f"  Обязательный Новогодний Ужин (31.12): {ny_dinner_total_cost:,.0f} IDR")
                            ny_remark = str(record_for_ny_dinner_lookup.get(HEADER_KEY_REMNYD, '')).strip()
                            if ny_remark: special_offer_remarks_set.add(ny_remark)
        except Exception as e_nyd: print(f"!!! ОШИБКА В БЛОКЕ НГ УЖИНА: {type(e_nyd).__name__} - {e_nyd}"); print(traceback.format_exc())
        if not found_rates_for_all_nights: calculation_details_temp.append("\n<b>Внимание:</b> Не удалось найти тарифы для всех ночей...")
        calculation_details_temp.append(f"\n<b>Итого базовая стоимость номера: {total_room_cost_idr:,.0f} IDR</b>")
        if surcharge_details_parts_temp:
            calculation_details_temp.append("\n<b>Дополнительные услуги и доплаты:</b>"); calculation_details_temp.extend(surcharge_details_parts_temp); calculation_details_temp.append(f"<b>Итого доплаты: {total_surcharges_idr:,.0f} IDR</b>")
        grand_total_idr = total_room_cost_idr + total_surcharges_idr
        
        # --- ИЗМЕНЕНИЕ: Вывод новых ремарок ---
        if general_remarks_set: 
            calculation_details_temp.append("\n<b>Включено в проживание:</b>")
            calculation_details_temp.extend(f"<i>- {remark}</i>" for remark in general_remarks_set)
        if policy_remarks_set: 
            calculation_details_temp.append("\n<b>Примечания по размещению детей:</b>")
            calculation_details_temp.extend(f"<i>- {remark}</i>" for remark in policy_remarks_set)
        if special_offer_remarks_set: 
            calculation_details_temp.append("\n<b>Примечания и спецпредложения:</b>")
            calculation_details_temp.extend(f"<i>- {remark}</i>" for remark in special_offer_remarks_set)
        if cancellation_policy_set:
            calculation_details_temp.append("\n<b>Условия аннуляции:</b>")
            calculation_details_temp.extend(f"<i>- {remark}</i>" for remark in cancellation_policy_set)
            
        calculation_details_temp.append(f"\n<b>ОБЩАЯ РАССЧИТАННАЯ СТОИМОСТЬ: {grand_total_idr:,.0f} IDR</b>")
        if usd_rate > 0 and grand_total_idr > 0:
            grand_total_usd = grand_total_idr / usd_rate; avg_daily_usd = grand_total_usd / num_nights
            calculation_details_temp.append("<hr>"); calculation_details_temp.append(f"<b>Стоимость в USD (курс {usd_rate:,.2f}):</b>"); calculation_details_temp.append(f"<b>ИТОГО: ${grand_total_usd:,.2f} USD</b>"); calculation_details_temp.append(f"<b>Средняя стоимость за ночь: ${avg_daily_usd:,.2f} USD</b>")
        calculation_output_lines.extend(calculation_details_temp)
    except Exception as e_outer: 
        calculation_output_lines.append(f"<b>Произошла непредвиденная критическая ошибка ({type(e_outer).__name__}).</b>"); print(f"Критическая внешняя ошибка: {type(e_outer).__name__} - {e_outer}"); print(traceback.format_exc())
    return calculation_output_lines

# --- Flask-приложение ---
app = Flask(__name__)

@app.route('/')
def index():
    hotel_data = get_structured_hotel_data()
    regions = sorted(hotel_data.keys())
    return render_template('index.html', regions=regions, all_hotel_data=hotel_data, user_input=None)

@app.route('/calculate_price', methods=['POST'])
def handle_calculation():
    if request.method == 'POST':
        user_data_from_form = {key: request.form.get(key) for key in request.form}
        error_msg_form = None
        try:
            if user_data_from_form.get('checkin_date'):
                dt_obj_checkin = datetime.strptime(user_data_from_form['checkin_date'], '%Y-%m-%d')
                user_data_from_form['checkin_date'] = dt_obj_checkin.strftime('%d.%m.%Y')
            else: error_msg_form = "Дата заезда не указана."
            if not error_msg_form and user_data_from_form.get('checkout_date'):
                dt_obj_checkout = datetime.strptime(user_data_from_form['checkout_date'], '%Y-%m-%d')
                user_data_from_form['checkout_date'] = dt_obj_checkout.strftime('%d.%m.%Y')
            elif not error_msg_form: error_msg_form = "Дата выезда не указана."
            if not error_msg_form:
                temp_adults_count = user_data_from_form.get('adults_count', '0'); temp_children_count = user_data_from_form.get('children_count', '0')
                if not temp_adults_count.isdigit() or int(temp_adults_count) <= 0: error_msg_form = "Количество взрослых должно быть положительным числом."
                else: user_data_from_form['adults_count'] = int(temp_adults_count)
                if not error_msg_form:
                    if not temp_children_count.isdigit() or int(temp_children_count) < 0: error_msg_form = "Количество детей должно быть числом (0 или больше)."
                    else: user_data_from_form['children_count'] = int(temp_children_count)
        except ValueError: error_msg_form = "Ошибка в формате дат или количества гостей."
        hotel_data = get_structured_hotel_data()
        regions = sorted(hotel_data.keys())
        if error_msg_form: return render_template('index.html', error_message=error_msg_form, regions=regions, all_hotel_data=hotel_data)
        calculation_result_html_list = calculate_price_for_web(user_data_from_form)
        result_html_string = "<br>".join(calculation_result_html_list) 
        return render_template('index.html', calculation_result_html=result_html_string, user_input=user_data_from_form, regions=regions, all_hotel_data=hotel_data)
    return "This route only accepts POST requests."

# --- Запуск Flask-приложения ---
if __name__ == '__main__':
    app.run(debug=True)