from flask import Flask,jsonify,request,render_template
import requests
import settings
import datetime
import redis

r = redis.Redis(decode_responses=True)

app = Flask(__name__, static_url_path='/xmrmining')

def replace_apostrophe(nano_address):
#    return nano_address.replace("'", "")
    return nano_address

@app.route("/xmrmining/workers", methods = ['GET'])
def get_workers():
    if(request.method == 'GET'):
        x = requests.get('http://{}/1/workers'.format(settings.proxyapi_url))
        worker_json = x.json()
        worker_list = {}
        for worker in worker_json['workers']:
            print(worker)
            worker_list[worker[0]] = (worker[2], worker[3], worker[7], worker[10])


    return jsonify(worker_list)

@app.route("/xmrmining")
def main_website():

    if settings.main_pool == 'moneroocean':
        main_pool_url = 'https://api.moneroocean.stream/miner/{}/stats'.format(settings.mining_address)
    elif settings.main_pool == 'supportxmr':
        main_pool_url = 'https://supportxmr.com/api/miner/{}/stats'.format(settings.mining_address)

    try:
        pool_details = requests.get(main_pool_url)
        pool_amount = float(pool_details.json()['amtDue']) / 1000000000000.0
        percentage_amount = (pool_amount / 0.02) * 100
    except:
        pool_amount = 0
        percentage_amount = 0


    pool_status = r.get('pool_status')

    x = requests.get('http://{}/1/workers'.format(settings.proxyapi_url))
    worker_json = x.json()
    worker_list = []
    time_now = datetime.datetime.now()
    total_hash = 0
    for worker in worker_json['workers']:
#        print(worker)
        if len(worker[0]) == 65 and worker[0][:5] == 'nano_':
            time_str = str(worker[7])
            try:
                time_int = int(time_str[:-3])
            except:
                time_int = 0
            converted_last_share = datetime.datetime.fromtimestamp(time_int)
            time_since = time_now - converted_last_share
            total_hash = total_hash + int(worker[10])

            current_shares = int(worker[3])
            worker_address = worker[0]
            # Calculate accepted shares for this round
            if r.exists(worker_address):
                total_worker_shares = int(r.get(worker_address))
            else:
                total_worker_shares = 0

            accepted_shares = current_shares - total_worker_shares

            worker_list.append([replace_apostrophe(worker[0]),worker[2], worker[3], converted_last_share, time_since, worker[10], accepted_shares])

    return render_template('index.html', name=worker_list, total_hash=total_hash, amtDue=pool_amount, percentage_amount=percentage_amount, pool_status=pool_status)
