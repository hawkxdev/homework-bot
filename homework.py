import logging
import os
import sys
import time
from http import HTTPStatus
from json import JSONDecodeError
from logging import StreamHandler

import requests
from dotenv import load_dotenv
from telebot import TeleBot

from exceptions import EndpointUnavailableError, TokenNotFoundError

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600  # 10 минут в секундах
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.DEBUG,
    handlers=[StreamHandler(stream=sys.stdout)],
)


def check_tokens() -> None:
    """Проверяет доступность переменных окружения.

    Raises:
        TokenNotFoundError: Если отсутствует любой из обязательных токенов.
    """
    if not PRACTICUM_TOKEN:
        raise TokenNotFoundError(
            'Отсутствует PRACTICUM_TOKEN: токен API сервиса Практикум.Домашка'
        )
    if not TELEGRAM_TOKEN:
        raise TokenNotFoundError(
            'Отсутствует TELEGRAM_TOKEN: токен телеграм бота'
        )
    if not TELEGRAM_CHAT_ID:
        raise TokenNotFoundError(
            'Отсутствует TELEGRAM_CHAT_ID: id телеграм чата'
        )


def send_message(bot: TeleBot, message: str) -> None:
    """Отправляет сообщение в телеграм чат."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug(f'Бот отправил сообщение: {message}')
    except Exception as error:
        logging.error(f'Сбой при отправке сообщения в Telegram: {error}')


def get_api_answer(timestamp: int) -> dict:
    """Делает запрос к эндпоинту API-сервиса.

    Raises:
        EndpointUnavailableError: Если эндпоинт недоступен.
    """
    try:
        response = requests.get(
            url=ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp},
            timeout=30,
        )
    except requests.RequestException as error:
        logging.error(f'Сбой при запросе к эндпоинту: {error}')
        raise
    except Exception as error:
        logging.error(f'Сбой при запросе к эндпоинту: {error}')
        raise
    if response.status_code != HTTPStatus.OK:
        msg = (
            f'Эндпоинт {ENDPOINT} недоступен. '
            f'Код ответа API: {response.status_code}'
        )
        logging.error(msg)
        raise EndpointUnavailableError(msg)
    try:
        response_dict = response.json()
    except JSONDecodeError as error:
        logging.error(
            f'Ошибка преобразования JSON к типам данных Python: {error}'
        )
        raise
    return response_dict


def check_response(response: dict) -> None:
    """Проверяет ответ API на соответствие документации."""
    # Добавил из-за pytest но считаю проверку на dict избыточной
    if not isinstance(response, dict):
        msg = 'Ответ API не является словарем'
        logging.error(msg)
        raise TypeError(msg)

    if 'homeworks' not in response:
        msg = 'В ответе API отсутствует ключ "homeworks"'
        logging.error(msg)
        raise KeyError(msg)
    if 'current_date' not in response:
        msg = 'В ответе API отсутствует ключ "current_date"'
        logging.error(msg)
        raise KeyError(msg)
    if not isinstance(response['homeworks'], list):
        msg = 'Значение по ключу "homeworks" не является списком'
        logging.error(msg)
        raise TypeError(msg)


def parse_status(homework: dict) -> str:
    """Извлекает из ответа API статус домашней работы."""
    required_keys = {
        'id',
        'status',
        'homework_name',
        'reviewer_comment',
        'date_updated',
        'lesson_name',
    }
    if not required_keys.issubset(homework):
        missing = required_keys - homework.keys()
        msg = f'В homework отсутствуют ключи: {missing}'
        logging.error(msg)
        raise KeyError(msg)

    homework_name = homework['homework_name']
    if not homework_name:
        homework_id = homework['id']
        msg = f'Название домашней работы с id={homework_id} не указано'
        logging.error(msg)
        raise ValueError(msg)

    status = homework['status']
    if status not in HOMEWORK_VERDICTS:
        msg = f'Неожиданный статус домашней работы "{status}"'
        logging.error(msg)
        raise ValueError(msg)

    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    try:
        check_tokens()
    except TokenNotFoundError as error:
        logging.critical(error)
        return

    bot = TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    logging.info('Бот успешно запущен!')
    last_error = ''

    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)

            homeworks = response['homeworks']
            timestamp = response['current_date']

            if not homeworks:
                logging.debug('В ответе API новые статусы отсутствуют.')

            for homework in homeworks:
                msg = parse_status(homework)
                send_message(bot, msg)

        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logging.error(message)
            if last_error != message:
                send_message(bot, message)
                last_error = message

        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
