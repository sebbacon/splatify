# Deployment

Create an app:

dokku apps:create splatify

Because this uses a cron job (see `app.json`):

    dokku cron:set --global mailto <your_email>

Set up persistent storage:

    dokku storage:ensure-directory splatify
    dokku storage:mount splatify  /var/lib/dokku/data/storage/splatify:/app/data

Set the dokku server up as a remote:

    git remote add dokku dokku@your-server:splatify

Deploy:

    git push dokku main
