from monero.wallet import Wallet
from monero.backends.jsonrpc import JSONRPCWallet
import time
import requests
from decimal import *
getcontext().prec = 30
from jcnanolib import nano 
import settings

w = Wallet(JSONRPCWallet(port=28088))

import redis

r = redis.Redis(decode_responses=True)

monero_address = w.address()
monero_balance = w.balance()

print(monero_address)
print(monero_balance)

nano_address = settings.deposit_address
wallet_seed = settings.wallet_seed
index_pos = settings.index

last_block = 0
if r.exists('last_block'):
    last_block = r.get('last_block')
else:
    r.set('last_block', 0)
    last_block = 0

print('Waiting for XMR deposit')

while True:
    last_transaction = w.incoming(min_height=int(last_block))
    if len(last_transaction) > 0:
        print(last_transaction)
        print('Setting last_block')
        last_block = int(last_transaction[0].transaction.height) + 1
        r.set('last_block', last_block)
        r.set('last_amount', str(last_transaction[0].amount))

        print('Get latest pool data')
        x = requests.get('http://localhost:44733/1/workers')
        worker_json = x.json()

        total_shares = 0
        worker_shares = {}
        for worker in worker_json['workers']:
#            print('{} {}'.format(worker[0], worker[3]))

            current_shares = int(worker[3])
            # Calculate accepted shares for this round
            if r.exists(worker[0]):
                total_worker_shares = int(r.get(worker[0]))
            else:
                total_worker_shares = 0

            accepted_shares = current_shares - total_worker_shares

            # Add to our dict
            worker_shares[worker[0]] = accepted_shares

            # Store in Redis the total accepted shares 
            r.set(worker[0], current_shares)
            # Store in Redis the accepted shares for this round
            r.set('{}-shares-{}'.format(str(last_block), worker[0]), accepted_shares)

            total_shares = total_shares + accepted_shares

        check_total = 0
        nano_total_amount_raw = 0

        for worker in worker_shares:
            while nano_total_amount_raw == 0:
                # Nano amount (we will get this by parsing account)
                result = nano.process_pending(nano_address, index_pos, wallet_seed)
                print(result)
                nano_total_amount_raw = nano.get_account_balance(nano_address)


            # Calculate share
            nano_share_raw = Decimal(nano_total_amount_raw) * (Decimal(worker_shares[worker]) / Decimal(total_shares))
            print('{} {} {} {} {}'.format(worker, worker_shares[worker], total_shares, nano_share_raw, nano_total_amount_raw))

            # Send share of Nano to worker
            result = nano.send_xrb(worker, nano_share_raw, nano_address, index_pos, wallet_seed)
            print(result)

            # Add up all the shares to check that it matches original amount
            check_total = check_total + nano_share_raw

            r.set('{}-nano-{}'.format(str(last_block), worker), int(nano_share_raw))

        if Decimal(check_total) == Decimal(nano_total_amount_raw):
            check_adds_up = True
        else:
            check_adds_up = False

        print('{} {} {}'.format(int(check_total), nano_total_amount_raw, check_adds_up ))

    time.sleep(5)





#Now send
#dest_account = 'nano_1kd4h9nqaxengni43xy9775gcag8ptw8ddjifnm77qes1efuoqikoqy5sjq3'
#raw_amount = 1000000000
