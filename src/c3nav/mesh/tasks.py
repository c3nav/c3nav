from asgiref.sync import async_to_sync

from c3nav.celery import app


@app.task(bind=True, max_retries=3)
def send_channel_msg(self, layer, msg):
    print("task sending channel msg...")
    async_to_sync(self.channel_layer.send)(layer, msg)
