import random
from flask import Flask
from flask_socketio import SocketIO, emit

app = Flask(__name__, static_folder='.', static_url_path='')
app.config['SECRET_KEY'] = 'avalon_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# 玩家資料結構: { name: { 'vote': '反對', 'role': None, 'viewed': False } }
players = {} 
current_quest = 1
current_attempt = 1
current_captain = "尚未設定"
current_team_list = []
history_records = []
mission_outcomes = {}
game_started = False

# 任務投票階段的專用變數
mission_voting_active = False
mission_team = []
voted_members = []
mission_votes = []
opened_missions = [] # 記錄已經點開任務卡的玩家

# 阿瓦隆配置表 (總人數: (好人總數, 壞人總數))
GAME_CONFIG = {
    5: (3, 2), 6: (4, 2), 7: (4, 3), 8: (5, 3), 9: (6, 3), 10: (6, 4)
}

def get_status():
    return [{'name': name, 'vote': data['vote'], 'viewed': data['viewed']} for name, data in players.items()]

def get_game_info():
    return {
        'quest': current_quest,
        'attempt': current_attempt,
        'player_count': len(players),
        'captain': current_captain,
        'team': current_team_list,
        'game_started': game_started,
        'config': GAME_CONFIG.get(len(players), (0,0)),
        'mission_voting_active': mission_voting_active,
        'mission_team': mission_team,
        'voted_members': voted_members,
        'opened_missions': opened_missions
    }

@app.route('/')
def index():
    return app.send_static_file('index.html')

@socketio.on('connect')
def handle_connect():
    emit('update_game_info', get_game_info())
    emit('update_status', get_status())
    emit('update_history', {'history': history_records, 'outcomes': mission_outcomes})

@socketio.on('add_player')
def handle_add_player(name):
    if not game_started and name and name not in players:
        players[name] = {'vote': '反對', 'role': None, 'viewed': False}
        emit('update_status', get_status(), broadcast=True)
        emit('update_game_info', get_game_info(), broadcast=True)

@socketio.on('remove_player')
def handle_remove_player(name):
    global current_captain
    if not game_started and name in players:
        del players[name]
        if current_captain == name: current_captain = "尚未設定"
        if name in current_team_list: current_team_list.remove(name)
        # 清除歷史中該玩家的投票紀錄避免前端報錯
        for record in history_records:
            if name in record.get('votes', {}): del record['votes'][name]
        emit('update_status', get_status(), broadcast=True)
        emit('update_game_info', get_game_info(), broadcast=True)
        emit('update_history', {'history': history_records, 'outcomes': mission_outcomes}, broadcast=True)

@socketio.on('toggle_game_state')
def handle_toggle_game_state():
    global game_started, mission_voting_active
    game_started = False
    mission_voting_active = False
    for n in players:
        players[n]['role'] = None
        players[n]['viewed'] = False
    emit('update_game_info', get_game_info(), broadcast=True)
    emit('update_status', get_status(), broadcast=True)

@socketio.on('start_game_with_roles')
def handle_start_game(selected_roles):
    global game_started
    player_names = list(players.keys())
    random.shuffle(player_names)
    
    for i, name in enumerate(player_names):
        players[name]['role'] = selected_roles[i]
        players[name]['viewed'] = False
        
    game_started = True
    emit('update_game_info', get_game_info(), broadcast=True)
    emit('update_status', get_status(), broadcast=True)

@socketio.on('view_role')
def handle_view_role(name):
    if name not in players or players[name]['role'] is None: return
    
    role = players[name]['role']
    players[name]['viewed'] = True
    
    info = ""
    evil_team = [p for p, d in players.items() if d['role'] in ['刺客', '莫甘娜', '莫德雷德', '莫德雷德的爪牙']]
    merlin_sees = [p for p, d in players.items() if d['role'] in ['刺客', '莫甘娜', '奧伯倫', '莫德雷德的爪牙']]
    percival_sees = [p for p, d in players.items() if d['role'] in ['梅林', '莫甘娜']]
    
    if role == '梅林':
        info = f"你看到的壞人有：{', '.join(merlin_sees)}" if merlin_sees else "你沒看到任何壞人。"
    elif role == '派西維爾':
        info = f"你看到梅林或莫甘娜可能是：{', '.join(percival_sees)}" if percival_sees else "你沒看到任何人。"
    elif role in ['刺客', '莫甘娜', '莫德雷德', '莫德雷德的爪牙']:
        others = [p for p in evil_team if p != name]
        info = f"你的隊友有：{', '.join(others)}" if others else "你沒有其他隊友。"
    elif role == '奧伯倫':
        info = "你無法看到隊友，隊友也看不到你。"
    else:
        info = "你沒有任何額外資訊。"

    emit('role_info_result', {'name': name, 'role': role, 'info': info})
    emit('update_status', get_status(), broadcast=True)

@socketio.on('toggle_vote')
def handle_toggle_vote(name):
    if not mission_voting_active and name in players:
        players[name]['vote'] = '贊成' if players[name]['vote'] == '反對' else '反對'
        emit('update_status', get_status(), broadcast=True)

@socketio.on('toggle_captain')
def handle_toggle_captain(name):
    global current_captain
    if not mission_voting_active:
        current_captain = name
        emit('update_game_info', get_game_info(), broadcast=True)

@socketio.on('toggle_mission_member')
def handle_toggle_mission(name):
    global current_team_list
    if not mission_voting_active:
        if name in current_team_list: current_team_list.remove(name)
        else: current_team_list.append(name)
        emit('update_game_info', get_game_info(), broadcast=True)

@socketio.on('submit_round')
def handle_submit_round():
    global current_attempt, current_captain, current_team_list
    global mission_voting_active, mission_team, voted_members, mission_votes, opened_missions
    if not players: return

    approve_count = sum(1 for d in players.values() if d['vote'] == '贊成')
    is_approved = approve_count > (len(players) / 2)
    
    record = {
        'quest': current_quest, 'attempt': current_attempt,
        'captain': current_captain, 'team': list(current_team_list),
        'votes': {n: d['vote'] for n, d in players.items()},
        'is_approved': is_approved
    }
    history_records.append(record)
    
    if is_approved:
        # 提案通過，進入出任務鎖定階段
        mission_voting_active = True
        mission_team = list(current_team_list)
        voted_members = []
        mission_votes = []
        opened_missions = []
    else:
        # 提案失敗，重置隊長與隊員，推進次數
        current_attempt += 1
        current_captain = "尚未設定"
        current_team_list = []
    
    for n in players: players[n]['vote'] = '反對'
    
    emit('update_status', get_status(), broadcast=True)
    emit('update_game_info', get_game_info(), broadcast=True)
    emit('update_history', {'history': history_records, 'outcomes': mission_outcomes}, broadcast=True)

@socketio.on('request_mission_modal')
def handle_request_mission_modal(name):
    # 防堵重複點擊與多設備同時點擊
    if not mission_voting_active or name not in mission_team or name in voted_members or name in opened_missions: 
        return
    
    # 紀錄已被點開
    opened_missions.append(name)
    
    # 廣播更新，將該玩家按鈕鎖定為「👀 投票中...」
    emit('update_game_info', get_game_info(), broadcast=True)
    emit('update_status', get_status(), broadcast=True)
    
    role = players[name].get('role', '')
    is_good = role in ['梅林', '派西維爾', '亞瑟的忠臣']
    emit('open_mission_modal', {'name': name, 'is_good': is_good})

@socketio.on('submit_individual_mission_vote')
def handle_submit_individual_mission_vote(data):
    global mission_voting_active, current_quest, current_attempt
    global current_captain, current_team_list, mission_team, voted_members, mission_votes, opened_missions
    
    name = data.get('name')
    vote = data.get('vote')
    
    if not mission_voting_active or name not in mission_team or name in voted_members: return
    
    # 雙重防護：好人不能出失敗
    role = players[name].get('role', '')
    is_good = role in ['梅林', '派西維爾', '亞瑟的忠臣']
    if is_good and vote == '失敗':
        vote = '成功'
        
    voted_members.append(name)
    mission_votes.append(vote)
    
    emit('update_game_info', get_game_info(), broadcast=True)
    emit('update_status', get_status(), broadcast=True)
    
    if len(voted_members) == len(mission_team):
        mission_voting_active = False
        # 將任務結果重新排序後再寫入歷史紀錄，避免依照投票順序顯示而暴露誰投失敗票。
        # 顯示規則：失敗票一律在最前面，成功票排在後面。
        fails = mission_votes.count('失敗')
        mission_outcomes[current_quest] = ['失敗'] * fails + ['成功'] * (len(mission_votes) - fails)
        
        if fails == 0:
            result_msg = "本次任務執行成功！"
        else:
            result_msg = f"任務失敗！出現了 {fails} 張失敗票！"
            
        emit('mission_result_animation', {'message': result_msg, 'fails': fails}, broadcast=True)
        
        current_quest += 1
        current_attempt = 1
        current_captain = "尚未設定"
        current_team_list = []
        mission_team = []
        voted_members = []
        mission_votes = []
        opened_missions = []
        
        emit('update_status', get_status(), broadcast=True)
        emit('update_game_info', get_game_info(), broadcast=True)
        emit('update_history', {'history': history_records, 'outcomes': mission_outcomes}, broadcast=True)

@socketio.on('reset_history')
def handle_reset_history():
    global current_quest, current_attempt, current_captain, current_team_list, game_started
    global mission_voting_active, mission_team, voted_members, mission_votes, opened_missions
    
    history_records.clear()
    mission_outcomes.clear()
    
    current_quest, current_attempt = 1, 1
    current_captain, current_team_list = "尚未設定", []
    mission_voting_active = False
    mission_team, voted_members, mission_votes, opened_missions = [], [], [], []
    game_started = False
    for n in players: 
        players[n]['vote'] = '反對'
        players[n]['role'] = None
        players[n]['viewed'] = False
    emit('update_status', get_status(), broadcast=True)
    emit('update_game_info', get_game_info(), broadcast=True)
    emit('update_history', {'history': history_records, 'outcomes': mission_outcomes}, broadcast=True)

@socketio.on('three_fails')
def handle_three_fails():
    roles = {name: data['role'] for name, data in players.items()}
    emit('reveal_all_roles', roles, broadcast=True)

@socketio.on('three_successes')
def handle_three_successes():
    good_players = [name for name, data in players.items() if data['role'] in ['梅林', '派西維爾', '亞瑟的忠臣']]
    evil_info = {name: data['role'] for name, data in players.items() if data['role'] in ['刺客', '莫甘娜', '莫德雷德', '奧伯倫', '莫德雷德的爪牙']}
    emit('trigger_assassination', {'good_players': good_players, 'evil_info': evil_info}, broadcast=True)

@socketio.on('submit_assassination')
def handle_assassination(target_name):
    if target_name not in players: return
    is_merlin = (players[target_name]['role'] == '梅林')
    result_msg = f"刺殺對象為 {target_name}。\n" + ("刺殺成功，壞人獲勝！" if is_merlin else "刺殺失敗，好人獲勝！")
    emit('assassination_result', {'message': result_msg, 'is_evil_win': is_merlin}, broadcast=True)
    roles = {name: data['role'] for name, data in players.items()}
    emit('reveal_all_roles', roles, broadcast=True)

@socketio.on('reorder_players')
def handle_reorder_players(data):
    global players
    dragged = data.get('dragged')
    target = data.get('target')

    if dragged in players and target in players:
        names = list(players.keys())
        dragged_idx = names.index(dragged)
        target_idx = names.index(target)
        
        names.remove(dragged)
        new_target_idx = names.index(target)
        
        if dragged_idx > target_idx:
            names.insert(new_target_idx, dragged)
        else:
            names.insert(new_target_idx + 1, dragged)
            
        new_players = {n: players[n] for n in names}
        players.clear()
        players.update(new_players)
        
        emit('update_status', get_status(), broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
