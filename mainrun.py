#TODO
# Add api
# Store block shares in single redis (json?)
# Regularly store worker shares in case proxy reset

from monero.wallet import Wallet
from monero.backends.jsonrpc import JSONRPCWallet

import time, requests, sys, redis, logging, datetime
from decimal import *
getcontext().prec = 30
from jcnanolib import nano

sys.path.append( 'changenow-api-python' )
from changenow_api.client import api_wrapper
from changenow_api.exceptions import ChangeNowApiError

import settings

w = Wallet(JSONRPCWallet(port=28088))

r = redis.Redis(decode_responses=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger()

monero_address = w.address()
monero_balance = w.balance()

logging.info(monero_address)
logging.info(monero_balance)

nano_address = settings.deposit_address
wallet_seed = settings.wallet_seed
index_pos = settings.index

api_key = settings.api_key

def min_exchange(from_ticker):
    try:
        response = api_wrapper('MIN_AMOUNT', from_ticker=from_ticker, to_ticker='nano')
    except ChangeNowApiError as err:
        logging.info(err)
    return response

def transaction_status(transaction_id, api_key):
    try:
        response = api_wrapper('TX_STATUS',  api_key=api_key, id=transaction_id)
    except ChangeNowApiError as err:
        logging.info(err)
    return response

def check_estimate(from_ticker, amount, api_key):
    try:
        response = api_wrapper('ESTIMATED', fixed_rate=False, api_key=api_key, from_ticker=from_ticker, amount=str(amount), to_ticker='nano')
    except ChangeNowApiError as err:
        logging.info(err)
    return response

def send_transaction(from_ticker, amount, nano_address, api_key):
    try:
        response = api_wrapper('CREATE_TX', address=nano_address, fixed_rate=False, api_key=api_key, from_ticker=from_ticker, amount=float(amount), to_ticker='nano')
    except ChangeNowApiError as err:
        logging.info(err)
    return response

# strip ' ' from nano addresses (windows)
def replace_apostrophe(nano_address):
    return nano_address.replace("'", "")

def update_status(status):
    r.set('pool_status', '{} {}'.format(datetime.datetime.now(), status))

def save_pool_state():
    logging.info('Saving Pool State')
    x = requests.get('http://{}/1/workers'.format(settings.proxyapi_url))
    worker_json = x.json()
    for worker in worker_json['workers']:
        if len(worker[0]) == 65 and worker[0][:5] == 'nano_':
            current_shares = int(worker[3])
            worker_address = worker[0]
            # Calculate accepted shares for this round
            if r.exists(worker_address):
                total_worker_shares = int(r.get(worker_address))
            else:
                total_worker_shares = 0

            round_shares = current_shares - total_worker_shares

            if r.exists("state-{}".format(worker_address)):
                update_worker_state(worker_address, "total_shares", int(total_worker_shares))
                update_worker_state(worker_address, "round_shares", int(round_shares))
                update_worker_state(worker_address, "current_shares", int(current_shares))

            else:
                result = r.hset("state-{}".format(worker_address),mapping={
                    "address": str(worker_address),
                    "total_shares": int(total_worker_shares),
                    "round_shares": int(round_shares),
                    "last_payout" : 0,
                    "last_hash" : "0",
                    "last_round" : 0,
                    "last_shares" : 0,
                    "last_block" : 0,
                    "current_shares": int(current_shares)
                })

def update_worker_state(worker, key, data):
    r.hset("state-{}".format(worker), key, data)

approx_fee = 0.0001
from_ticker = 'xmr'

logging.info('Rx all Nano')
result = nano.process_pending(nano_address, index_pos, wallet_seed)
logging.info(result)

if r.exists('last_block'):
    last_block = r.get('last_block')
else:
    r.set('last_block', 0)
    last_block = 0

if r.exists('round'):
    round = r.get('round')
else:
    r.set('round', 0)
    round = 0

logging.info('Waiting for XMR deposit')

while True:
    save_pool_state()
    # Check Minimum
    minimum_exchange = min_exchange(from_ticker)
    logging.info(minimum_exchange)

    monero_balance = w.balance()
    logging.info('XMR Balance: {}'.format(monero_balance))

    if Decimal(monero_balance) >= (Decimal(minimum_exchange['minAmount']) + Decimal(approx_fee)):

        last_transaction = w.incoming(min_height=int(last_block))
        if len(last_transaction) > 0:
            logging.info('{} {}'.format(last_transaction[0], w.confirmations(last_transaction[0])))
            if int(w.confirmations(last_transaction[0])) < 10:
                logging.info('await confirmation: {}'.format(int(w.confirmations(last_transaction[0]))))
                update_status('Confirming XMR payout from main pool')

                time.sleep(30)
                continue

            logging.info(last_transaction)
            logging.info('Setting last_block')

            last_block = int(last_transaction[0].transaction.height) + 1
            r.set('last_block', last_block)
            r.set('last_amount', str(last_transaction[0].amount))

            check_total = 0

            # Setup Exchange
            amount = Decimal(monero_balance) - Decimal(approx_fee)
            if r.exists('exchange_address'):
                logging.info('already have exchange address, get from redis')
                payinAddress = r.get('exchange_address')
            else:
                logging.info('get new exchange address')
                transaction_detail = send_transaction(from_ticker, str(amount), settings.deposit_address, api_key)
                logging.info(transaction_detail)
                transaction_id = transaction_detail['id']
                payinAddress = transaction_detail['payinAddress']
                r.set('exchange_address', payinAddress)

            try:
                txs = w.transfer(payinAddress, Decimal(amount))
                logging.info(txs)
            except:
                logging.info('XMR not ready, transfer to exchange failed')
                time.sleep(10)
                continue

            update_status('Exchanging XMR to Nano')
            exchange_status = 'starting'
            while exchange_status != 'finished':
                status_response = transaction_status(transaction_id, api_key)
                exchange_status = status_response['status']
                update_status('Exchanging XMR to Nano: {}'.format(exchange_status))
                logging.info(exchange_status)
                time.sleep(10)
            else:
                r.delete('exchange_address')

            # TODO add timeout
            time.sleep(120)

            nano_total_amount_raw = 0
            while Decimal(nano_total_amount_raw) <= Decimal(1000000):
                # Nano amount (we will get this by parsing account)
                result = nano.process_pending(nano_address, index_pos, wallet_seed)
                logging.info(result)
                nano_total_amount_raw = Decimal(nano.get_account_balance(nano_address))

            time.sleep(5)
            nano_total_amount_raw = Decimal(nano.get_account_balance(nano_address))

            logging.info('Get latest pool data')
            x = requests.get('http://{}/1/workers'.format(settings.proxyapi_url))
            worker_json = x.json()

            total_shares = 0
            worker_shares = {}
            logging.info('Calculate Shares')
            for worker in worker_json['workers']:
                if len(worker[0]) == 65 and worker[0][:5] == 'nano_':
                    current_shares = int(worker[3])
                    worker_address = worker[0]
                    # Calculate accepted shares for this round
                    if r.exists(worker_address):
                        total_worker_shares = int(r.get(worker_address))
                    else:
                        total_worker_shares = 0

                    accepted_shares = current_shares - total_worker_shares

                    # Add to our dict
                    worker_shares[worker_address] = accepted_shares

                    # Store in Redis the total accepted shares
                    r.set(worker_address, current_shares)
                    update_worker_state(worker, 'current_shares', int(current_shares))
                    update_worker_state(worker, 'last_block', int(last_block))

                    # Store in Redis the accepted shares for this round
                    r.set('{}-shares-{}'.format(str(last_block), worker_address), accepted_shares)
                    update_worker_state(worker, 'last_shares', int(accepted_shares))

                    total_shares = total_shares + accepted_shares


            update_status('Sending out Nano Payout')
            for worker in worker_shares:

                # Calculate share
                nano_share_raw = Decimal(nano_total_amount_raw) * (Decimal(worker_shares[worker]) / Decimal(total_shares))
                logging.info('{} {} {} {} {}'.format(worker, worker_shares[worker], total_shares, int(nano_share_raw), nano_total_amount_raw))

                # Send share of Nano to worker
                if Decimal(nano_share_raw) > Decimal(0):
                    if len(worker) == 65 and worker[:5] == 'nano_':
                        result = nano.send_xrb(worker, int(nano_share_raw), nano_address, index_pos, wallet_seed)
                        logging.info(result)
                        r.lpush('{}_payout'.format(last_block), str(worker))
                        r.set('{}-hash-{}'.format(str(last_block), worker), result['hash'])
                        update_worker_state(worker, 'last_hash', str(result['hash']))

                    else:
                        logging.info('Incorrect Address - not sending')

                # Add up all the shares to check that it matches original amount
                check_total = check_total + nano_share_raw

                r.set('{}-nano-{}'.format(str(last_block), worker), int(nano_share_raw))
                update_worker_state(worker, 'last_nano', int(nano_share_raw))

            if Decimal(check_total) == Decimal(nano_total_amount_raw):
                check_adds_up = True
            else:
                check_adds_up = False

            r.incr('round')
            logging.info('{} {} {}'.format(int(check_total), nano_total_amount_raw, check_adds_up ))

    update_status('Pool Mining (not reached payout threshold)')
    time.sleep(30)
