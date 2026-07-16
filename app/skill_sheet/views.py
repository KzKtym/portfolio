import json
import os
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Q
from .models import PersonalInfo, SkillSheetData
import unicodedata

def index(request):
    """デモ用: ID=1へリダイレクト"""
    return redirect('skill_sheet:detail', pk=1)


def detail(request, pk):
    """スキルシート詳細表示"""
    # パーソナル情報取得
    personal = get_object_or_404(PersonalInfo, pk=pk)
    
    # スキルシート取得（開始年月降順）
    skill_sheets = SkillSheetData.objects.filter(personal=personal).order_by('-start_month')
    
    # 設定ファイル読み込み
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # 検索キーワード取得
    search_query = request.GET.get('search', '').strip()
    search_query = unicodedata.normalize('NFKC', search_query)

    keywords = []
    search_results = {}
    highlighted_ids = []
    
    if search_query:
        # 全角・半角スペースで分割
        keywords = [kw for kw in search_query.replace('　', ' ').split(' ') if kw]
        
        # キーワードごとに検索
        for keyword in keywords:
            q = Q(project_name__icontains=keyword) | \
                Q(content__icontains=keyword) | \
                Q(lang__icontains=keyword) | \
                Q(db__icontains=keyword) | \
                Q(os__icontains=keyword) | \
                Q(tools__icontains=keyword) | \
                Q(remarks__icontains=keyword) | \
                Q(scope__icontains=keyword) | \
                Q(work_style__icontains=keyword)
            
            matched_sheets = skill_sheets.filter(q)
            
            # 案件数と実績合計計算
            count = matched_sheets.count()
            total_months = sum(sheet.duration for sheet in matched_sheets)
            years = total_months // 12
            months = total_months % 12
            
            # 実績合計の文字列生成
            if years > 0 and months > 0:
                duration_str = f"{years}年{months}ヶ月"
            elif years > 0:
                duration_str = f"{years}年"
            else:
                duration_str = f"{months}ヶ月"
            
            # 検索結果格納
            search_results[keyword] = {
                'count': count,
                'duration': duration_str,
                'projects': []
            }
            
            # マッチした案件をリストに追加
            for sheet in matched_sheets:
                # 全体のスキルシートでの位置を特定
                position = list(skill_sheets).index(sheet) + 1
                project_name = sheet.project_name
                if len(project_name) > 40:
                    project_name = project_name[:40] + '...'
                    
                # 開始年月・終了年月フォーマット
                start_date = f"{sheet.start_month[:4]}/{sheet.start_month[4:]}"
                end_date = f"{sheet.end_month[:4]}/{sheet.end_month[4:]}"
                
                # 期間フォーマット
                duration = sheet.duration
                if duration <= 12:
                    duration_str = f"{duration}ヶ月"
                else:
                    years = duration // 12
                    months = duration % 12
                    if months > 0:
                        duration_str = f"{years}年{months}ヶ月"
                    else:
                        duration_str = f"{years}年"
                
                
                search_results[keyword]['projects'].append({
                    'no': position,
                    'name': project_name,
                    'start_date': start_date,
                    'end_date': end_date,
                    'duration': duration_str                    
                })
                
                # ハイライト対象ID記録
                if sheet.id not in highlighted_ids:
                    highlighted_ids.append(sheet.id)
    
    # スキルシートデータ加工
    processed_sheets = []
    for idx, sheet in enumerate(skill_sheets, 1):
        # 開始年月・終了年月フォーマット
        start_date = f"{sheet.start_month[:4]}/{sheet.start_month[4:]}"
        end_date = f"{sheet.end_month[:4]}/{sheet.end_month[4:]}"
        
        # 期間フォーマット
        duration = sheet.duration
        if duration <= 12:
            duration_str = f"{duration}ヶ月"
        else:
            years = duration // 12
            months = duration % 12
            if months > 0:
                duration_str = f"{years}年{months}ヶ月"
            else:
                duration_str = f"{years}年"
        
        # リモート状況
        # if sheet.person1 == 0:
        #     remote_status = "※個人ワーク"
        # elif sheet.remote:
        #     remote_status = "※フルリモート"
        # else:
        #     remote_status = "" 
        
        # 人員フォーマット
        personnel = ""
        if sheet.person1 > 0:
            personnel = f"チーム {sheet.person1}名　開発 {sheet.person2}名　全体 {sheet.person3}名"
        
        # 担当工程
        processes = []
        for i in range(1, 8):
            if getattr(sheet, f'process{i}'):
                processes.append(config['Process'][str(i)])
        process_str = '　'.join(processes) if processes else '-'
        
        # データ整形（null/空白は"-"に変換）
        def format_value(value):
            return value if value else '-'
        
        processed_sheets.append({
            'no': idx,
            'id': sheet.id,
            'project_name': format_value(sheet.project_name),
            'start_date': start_date,
            'end_date': end_date,
            'duration': duration_str,
            # 'remote_status': remote_status,
            'remote_status': format_value(sheet.work_style),
            'content': format_value(sheet.content),
            'personnel': personnel,
            'lang': format_value(sheet.lang),
            'db': format_value(sheet.db),
            'os': format_value(sheet.os),
            'tools': format_value(sheet.tools),
            'processes': process_str,
            # 'scope': format_value(sheet.scope),
            'remarks': format_value(sheet.remarks),
            'highlighted': sheet.id in highlighted_ids
        })
    
    # パーソナル情報整形
    def format_personal_value(value):
        return value if value else '-'
    
    personal_data = {
        'registration_no': format_personal_value(personal.registration_no),
        'age': f"満{personal.age}歳",
        'gender': personal.get_gender_display() if personal.gender else '-',
        'education': format_personal_value(personal.education),
        'qualification': format_personal_value(personal.qualification),
        'availability': format_personal_value(personal.availability),
        'affiliation': format_personal_value(personal.affiliation),
        'nearest_station': format_personal_value(personal.nearest_station),
        'specialty_field': format_personal_value(personal.specialty_field),
        'specialty_tech': format_personal_value(personal.specialty_tech),
        'specialty_business': format_personal_value(personal.specialty_business),
        'self_pr': format_personal_value(personal.self_pr),
    }
    
    context = {
        'personal': personal_data,
        'skill_sheets': processed_sheets,
        'search_query': search_query,
        'keywords': keywords,
        'search_results': search_results,
    }
    
    return render(request, 'skill_sheet/main.html', context)