import channels
from asgiref.sync import async_to_sync

from c3nav.celery import app


@app.task(bind=True, max_retries=3)
def send_channel_msg(self, layer, msg):
    # todo: this is… not ideal, is it?
    print("task sending channel msg...")
    async_to_sync(channels.layers.get_channel_layer().send)(layer, msg)
