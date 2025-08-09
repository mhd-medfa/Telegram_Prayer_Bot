"""
reference:
 https://medium.com/@liuhh02
"""
import logging
from calendar import monthrange
from datetime import datetime, time, timedelta, timezone

import numpy as np
import requests
from bs4 import BeautifulSoup
from humanize import precisedelta
from telegram import ParseMode, Update
from telegram.ext import CallbackContext, CommandHandler, Updater

from config import settings
from dbhelper import DBHelper

prayer_names = ['Fajr', 'Sunrise', 'Dhuhr', 'Asr', 'Maghrib', 'Isha']

# Preparing for the database to store the  userids
db = DBHelper()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)
logger.info("Connected to database")

TOKEN = settings.TELEGRAM_BOT_TOKEN

updater = Updater(token=TOKEN, use_context=True)
dispatcher = updater.dispatcher
j = updater.job_queue

moscow = timezone(timedelta(hours=3))


def shift_time(time_str, delta: timedelta):
    """Manually advance or delay time by delta"""
    parts = time_str.split(':')
    hour = int(parts[0])
    minute = int(parts[1])
    time = datetime(2000, 1, 1, hour, minute)
    time += delta
    time = time.time()
    return f"{time.hour:02}:{time.minute:02}"


# Cache for prayer times with month/year tracking
_prayer_cache = {
    'data': None,
    'month': None,
    'year': None,
    'last_fetched': None
}

# Job tracking for each user to prevent duplicate notifications
_user_jobs = {}

# Type hints would be: Dict[str, Union[List[List[str]], int, datetime, None]]


def cancel_user_jobs(user_id):
    """Cancel all existing jobs for a specific user"""
    user_id = str(user_id)
    if user_id in _user_jobs:
        jobs_list = _user_jobs[user_id]
        for job in jobs_list[:]:  # Create a copy to iterate over
            try:
                job.schedule_removal()
                jobs_list.remove(job)
                logging.info(f'Cancelled job for user {user_id}')
            except Exception as e:
                logging.warning(f'Failed to cancel job for user {user_id}: {e}')
        # Clean up empty lists
        if not jobs_list:
            del _user_jobs[user_id]

def get_month_times():
    """Fetches the table of prayer times for the current month from umma.ru website"""
    now = datetime.now(moscow)
    current_month = now.month
    current_year = now.year
    
    # Check if we need to fetch new data
    if (_prayer_cache['data'] is None or 
        _prayer_cache['month'] != current_month or 
        _prayer_cache['year'] != current_year):
        
        logger.info(f"Fetching fresh prayer times for {current_year}-{current_month:02d}")
        
        try:
            url = "https://umma.ru/raspisanie-namaza/moscow"
            res = requests.get(url, verify=False, timeout=30)
            res.raise_for_status()  # Raise an exception for bad status codes
            
            html = res.content
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table')
            
            if table is None:
                raise Exception("No prayer time table found on the website")
            
            prayers = []
            rows_processed = 0
            
            for row in table.find_all("tr")[1:]:  # Skip header row
                cells = row.find_all("td")
                if len(cells) < 8:  # Ensure we have enough columns
                    continue
                    
                tmp = [tr.get_text().strip() for tr in cells][2:8]  # Extract prayer times
                
                if len(tmp) != 6:  # Ensure we have exactly 6 prayer times
                    continue
                
                # Apply time adjustments
                tmp[0] = shift_time(tmp[0], timedelta(minutes=-2))  # earlier fajr
                tmp[4] = shift_time(tmp[4], timedelta(minutes=2))  # later maghrib
                prayers.append(tmp)
                rows_processed += 1
            
            if rows_processed == 0:
                raise Exception("No valid prayer time rows found")
            
            # Update cache
            _prayer_cache['data'] = np.array(prayers).T.tolist()
            _prayer_cache['month'] = current_month
            _prayer_cache['year'] = current_year  
            _prayer_cache['last_fetched'] = now
            
            logger.info(f"Successfully cached {rows_processed} days of prayer times for {current_year}-{current_month:02d}")
            
        except Exception as e:
            logger.error(f"Failed to fetch prayer times: {e}")
            
            # If we have cached data from previous month, use it as fallback
            if _prayer_cache['data'] is not None:
                logger.warning(f"Using cached prayer times from {_prayer_cache['year']}-{_prayer_cache['month']:02d} as fallback")
                return _prayer_cache['data']
            else:
                logger.error("No cached data available, bot functions may fail")
                raise Exception(f"Unable to fetch prayer times and no cache available: {e}")
    
    return _prayer_cache['data']


def remind_next_prayer(context: CallbackContext):
    """Sends a message reminding about the prayer."""
    prayer_name = context.job.context['prayer_name']
    chat_id = context.job.context['chat_id']
    user = db.get_user(chat_id)
    if not user.active:
        return
    try:
        context.bot.send_message(chat_id=chat_id,
                                 text=f"It's time for {prayer_name}!")
    except:
        pass


def register_todays_prayers(context: CallbackContext):
    """Registers callbacks for all of today's prayers."""
    uid = context.job.context['chat_id']
    user = db.get_user(uid)
    if not user.active:
        return
    logging.info(f'Registering today\'s prayers for {uid}')
    
    # Initialize job tracking for this user if not exists
    if str(uid) not in _user_jobs:
        _user_jobs[str(uid)] = []
    
    prayer_times = get_month_times()
    today = datetime.now(moscow).day - 1
    for name, prayer_time in zip(prayer_names, prayer_times):
        prayer_time = prayer_time[today]
        timestamp = [int(x) for x in prayer_time.split(':')]
        timestamp = time(*timestamp, tzinfo=moscow)
        # Don't register past prayers
        if timestamp < datetime.now(moscow).time().replace(tzinfo=moscow):
            continue
        job = j.run_once(remind_next_prayer, timestamp, context={
            'chat_id': uid,
            'prayer_name': name,
        })
        
        # Store the job reference for later cancellation
        _user_jobs[str(uid)].append(job)

        logging.info(f'Registered callback for {name} for {uid} registered at {timestamp}')


def send_todays_times(update: Update, context: CallbackContext):
    times = get_month_times()
    today = datetime.now(moscow).day - 1
    prayers = [f"*{name}*: {time[today]}" for name, time in zip(prayer_names, times)]
    prayers_list = '\n'.join(prayers)
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text=f"Today's prayer times:\n{prayers_list}",
                             parse_mode=ParseMode.MARKDOWN_V2)


def send_tomorrows_times(update: Update, context: CallbackContext):
    times = get_month_times()
    now = datetime.now(moscow)
    _, days_in_month = monthrange(now.year, now.month)
    tomorrow = now.day
    if tomorrow >= days_in_month:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Sorry, this feature doesn't work"
                                      " on the last day of the month yet :(",
                                 parse_mode=ParseMode.MARKDOWN_V2)
        return
    prayers = [f"*{name}*: {time[tomorrow]}" for name, time in zip(prayer_names, times)]
    prayers_list = '\n'.join(prayers)
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text=f"Tomorrow's prayer times:\n{prayers_list}",
                             parse_mode=ParseMode.MARKDOWN_V2)


def send_next_prayer(update: Update, context: CallbackContext):
    times = get_month_times()
    now = datetime.now(moscow)
    today = now.day
    with_time = lambda p_time, day=today: now.replace(day=day, hour=int(p_time[:2]), minute=int(p_time[3:]))
    prayer_times = [with_time(time[today - 1]) for time in times]
    _, days_in_month = monthrange(now.year, now.month)
    tomorrow = now.day + 1
    if tomorrow < days_in_month + 1:
        prayer_times += [with_time(time[tomorrow - 1], tomorrow) for time in times]

    requested_prayer = None
    command = update.effective_message.text.split(' ', 1)
    if len(command) == 2:
        requested_prayer = command[1]
        if requested_prayer not in prayer_names:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="Unkown value for prayer time\n"
                                          f"Available values are: {', '.join(prayer_names)}",
                                     parse_mode=ParseMode.MARKDOWN_V2)
            return

    prayer_time = None
    if requested_prayer is None:
        prayer_time = next((p_time for p_time in prayer_times if p_time > now), None)
        if prayer_time is not None:
            requested_prayer = prayer_names[prayer_times.index(prayer_time) % len(prayer_names)]
    else:
        prayer_idx = prayer_names.index(requested_prayer)
        if prayer_idx + 1 < len(prayer_times):
            prayer_time = prayer_times[prayer_idx + 1]

    if prayer_time is None:
        requested_prayer = 'prayer' if requested_prayer is None else requested_prayer
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"Sorry, cannot find the next {requested_prayer} time\n"
                                      "Cannot cross the month boundary (yet)",
                                 parse_mode=ParseMode.MARKDOWN_V2)
        return
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text=f"The next {requested_prayer} is in {precisedelta(prayer_time - now)}"
                                  f" \\(at {prayer_time.strftime('%H:%M')}\\)",
                             parse_mode=ParseMode.MARKDOWN_V2)


def start(update: Update, context: CallbackContext):
    new_id = update.effective_chat.id
    context.chat_data['id'] = new_id
    user = db.get_user(new_id)
    
    # Cancel any existing jobs for this user to prevent duplicates
    cancel_user_jobs(new_id)
    
    if user is None:
        user = db.add_user(new_id)
    elif user.active:
        context.bot.send_message(chat_id=new_id,
                                 text="The bot is already activated.""")
        return
    elif not user.active:
        db.set_active(new_id, True)

    # Initialize job tracking for this user
    if str(new_id) not in _user_jobs:
        _user_jobs[str(new_id)] = []

    job = j.run_daily(register_todays_prayers, time(0, 0, tzinfo=moscow), context={
        'chat_id': new_id,
    })
    # Store the daily job reference
    _user_jobs[str(new_id)].append(job)
    
    job.run(dispatcher)  # Run just once (for today)
    context.bot.send_message(chat_id=new_id,
                             text="I will send you a reminder everyday on the prayer times of that day.\n"
                                  "Send /stop to stop reminding or /today to get just today's prayer times.")


def broadcast(update: Update, context: CallbackContext):
    if update.effective_chat.id == 619657404:
        users = db.list_users()
        for user in users:
            # logging.info(f"Sending {' '.join(context.args)} to user {user.id}")
            try:
                context.bot.send_message(chat_id=user.id, text=' '.join(context.args))
            except:
                continue


def stop(update: Update, context: CallbackContext):
    uid = update.effective_chat.id
    db.set_active(uid, False)
    
    # Cancel all scheduled jobs for this user
    cancel_user_jobs(uid)
    
    context.bot.send_message(chat_id=uid,
                             text="Reminders stopped. To reactivate, send /start again.")


start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)

today_handler = CommandHandler('today', send_todays_times)
dispatcher.add_handler(today_handler)

tomorrow_handler = CommandHandler('tomorrow', send_tomorrows_times)
dispatcher.add_handler(tomorrow_handler)

next_handler = CommandHandler('next', send_next_prayer)
dispatcher.add_handler(next_handler)

stop_handler = CommandHandler('stop', stop)
dispatcher.add_handler(stop_handler)

broadcast_handler = CommandHandler('broadcast', broadcast)
dispatcher.add_handler(broadcast_handler)

logger.info("Bot configured.")

users = db.list_users()
for user in users:
    # Initialize job tracking for existing users
    if str(user.id) not in _user_jobs:
        _user_jobs[str(user.id)] = []
    
    job = j.run_daily(register_todays_prayers, time(0, 0, tzinfo=moscow), context={
        'chat_id': user.id,
    })
    # Store the daily job reference
    _user_jobs[str(user.id)].append(job)
    job.run(dispatcher)  # Run just once (for today)

updater.start_polling()
