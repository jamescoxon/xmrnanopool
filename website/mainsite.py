from flask import Flask,jsonify,request,render_template
import requests
import settings
import datetime

app = Flask(__name__)

def replace_apostrophe(nano_address):
    return nano_address.replace("'", "")

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
    pool_details = requests.get('https://api.moneroocean.stream/miner/{}/stats'.format(settings.mining_address))
    pool_amount = float(pool_details.json()['amtDue']) / 1000000000000.0
    percentage_amount = (pool_amount / 0.02) * 100

    x = requests.get('http://{}/1/workers'.format(settings.proxyapi_url))
    worker_json = x.json()
    worker_list = []
    time_now = datetime.datetime.now()
    total_hash = 0
    for worker in worker_json['workers']:
#        print(worker)
        time_str = str(worker[7])
        try:
            time_int = int(time_str[:-3])
        except:
            time_int = 0
        converted_last_share = datetime.datetime.fromtimestamp(time_int)
        time_since = time_now - converted_last_share
        worker_list.append([replace_apostrophe(worker[0]),worker[2], worker[3], converted_last_share, time_since, worker[10]])
        total_hash = total_hash + int(worker[10])

    return render_template('index.html', name=worker_list, total_hash=total_hash, amtDue=pool_amount, percentage_amount=percentage_amount)
