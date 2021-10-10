import sys

import discord
import yaml

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from multiprocessing                import Process
from datetime import datetime, timedelta

class AutoDeleteCallBack:
    async def run(self, client, delete_older_than_minutes, channel_name, log_channel_name, guild_id):
        # Find the log channel
        log_channel = None
        guild = client.get_guild(guild_id)
        for channel in guild.channels:
            if channel.name == log_channel_name:
                log_channel = channel # todo: what if not found?

        # Run autodelete
        for channel in guild.channels:
            if channel.name == channel_name:
                prev_time = datetime.utcnow() - timedelta(minutes=delete_older_than_minutes)
                n_deleted = 0
                async for elem in channel.history(before = prev_time, oldest_first = True, limit = None):
                    print("Deleting message: " + str(elem))
                    await elem.delete()
                    n_deleted += 1
                await log_channel.send("Poistin kanavalta **#{}** viestit ennen ajanhetkeä {} UTC (yhteensä {} viestiä)".format(channel_name, prev_time.strftime("%Y-%m-%d %H:%M:%S"), n_deleted))

# An object of this class manages the bot for *one* server.
class MyBot:

    def __init__(self, instance_config, guild_id):
        print("Instance config:", instance_config)
        self.guild_id = guild_id
        self.autodel_config = instance_config["autodelete_channels"] # List of dicts {channel: X, callback_interval_minutes: Y, delete_older_than_minutes: Z] (todo: make channel a key)
        self.sched = AsyncIOScheduler()
        self.autodelete = AutoDeleteCallBack()
        self.jobs = dict() # channel name -> job
        self.log_channel_name = "bottikomennot" # todo: configiin?
        
    def set_autodel(self, channel_name, callback_interval_minutes, delete_older_than_minutes): # returns new autodel config
        # Check if autodelete is already active for the channel and if so, update config the values
        existing = False
        for i in range(len(self.autodel_config)):
            if self.autodel_config[i]["channel"] == channel_name:
                self.autodel_config[i]["callback_interval_minutes"] = callback_interval_minutes
                self.autodel_config[i]["delete_older_than_minutes"] = delete_older_than_minutes
                existing = True

        # Autodelete is not yet active for this channel
        if not existing:
            # Add new entry to the config
            self.autodel_config.append({"channel": channel_name, "callback_interval_minutes": callback_interval_minutes, "delete_older_than_minutes": delete_older_than_minutes})

        self.create_job(channel_name, callback_interval_minutes, delete_older_than_minutes) # Create new job

        print("Autodel config is now:", self.autodel_config)
        return self.autodel_config

    def create_job(self, channel_name, callback_interval_minutes, delete_older_than_minutes):
        if channel_name in self.jobs:
            self.jobs[channel_name].remove() # Terminate existing job

        self.jobs[channel_name] = self.sched.add_job(self.autodelete.run, 'interval', (client, delete_older_than_minutes, channel_name, self.log_channel_name, self.guild_id), minutes=callback_interval_minutes)

    def startup(self):
        print("Adding all jobs and starting the scheduler.")
        self.add_all_jobs()
        self.sched.start()

    def add_all_jobs(self):
        print("Adding all jobs")
        for X in self.autodel_config:
            self.create_job(X["channel"], X["delete_older_than_minutes"], X["callback_interval_minutes"])

    def trigger_all_jobs_now(self):
        print("Triggering all jobs")
        for channel_name in self.jobs:
            print("Trigger", channel_name)
            self.jobs[channel_name].modify(next_run_time=datetime.now())

    def get_settings_string(self):
        lines = []
        lines.append("**Autodelete-asetukset**")
        for job in self.autodel_config:
            lines.append("**#{}**: Poistan {} tunnin välein vähintään {} päivää vanhat viestit.".format(job["channel"], job["callback_interval_minutes"]//60, job["delete_older_than_minutes"]//(60*24)))
        return "\n".join(lines)

    #def save_config(self):
    #    config = {"token": self.token, "autodelete_channels": self.autodel_config}
    #    filename = "config_local.yaml"
    #    with open(filename, 'w') as outfile:
    #        yaml.dump(config, outfile, default_flow_style=False)
    #    print("Update config file", filename)

# Todo: Use channel objects instead of channel names

# Set to remember if the bot is already running, since on_ready may be called
# more than once on reconnects
this = sys.modules[__name__]
this.running = False

yaml_filename = "config_local.yaml"
global_config = yaml.safe_load(open(yaml_filename))
print("Global config:", global_config)

instances = dict() # Guild id -> MyBot object

# Initialize the client
print("Starting up...")
client = discord.Client()

# Define event handlers for the client
# on_ready may be called multiple times in the event of a reconnect,
# hence the running flag
@client.event
async def on_ready():
    if this.running: return
    else: this.running = True

    
    print("Bot started up.", flush=True)
    async for guild in client.fetch_guilds(limit=150):
        print("guild", guild.name, guild.id)

        if guild.id not in global_config["instances"]:
            global_config["instances"][guild.id] = {"autodelete_channels": []} # Init empty config for this guild

        instance = MyBot(global_config["instances"][guild.id], guild.id) # todo: this is a bit silly
        instance.startup()
        instances[guild.id] = instance
    print(instances)

@client.event
async def on_message(message):
    print("onmessage", message.content)
    mybot = instances[message.guild.id]
    if message.content.startswith("!ohjeet") and message.channel.name == "bottikomennot": # todo: check server also. Otherwise possiblity of cross-server commands.
        lines = []
        lines.append("**PolyamoriaSuomiBot**")
        lines.append("")
        lines.append("Komento **!ohjeet** tulostaa tämän käyttöohjeen. Komento **!asetukset** näyttää nykyiset asetukset. Muita komentoja ovat:")
        lines.append("")
        lines.append("**!autodelete** aseta [kanavan nimi ilman risuaitaa] [aikahorisontti päivinä] [kuinka monen tunnin välein poistot tehdään]")
        lines.append("**!autodelete** aja-nyt") # todo
        lines.append("**!autodelete** lopeta [kanavan nimi]") # todo
        lines.append("")
        lines.append("Esimerkiksi jos haluat asettaa kanavan #mielenterveys poistoajaksi 60 päivää siten, että poistot tehdään kerran päivässä, anna kirjoita komentokanavalle komento `!autodelete aseta mielenterveys 90 24`. Annetuiden numeroiden on oltava kokonaislukuja. Tällä komennolla voi myös muokata olemassaolevia asetuksia kanavalle. Jos haluat myöhemmin ottaa poiston pois päältä, anna komento `!autodelete lopeta mielenterveys`.")
        await message.channel.send("\n".join(lines))
    if message.content.startswith("!asetukset") and message.channel.name == "bottikomennot":
        await message.channel.send(mybot.get_settings_string())
    if message.content.startswith("!autodelete aja-nyt") and message.channel.name == "bottikomennot":
        mybot.trigger_all_jobs_now()
    if message.content.startswith("!autodelete aseta") and message.channel.name == "bottikomennot":
        tokens = message.content.split()

        # Check the number of parameters
        if len(tokens) != 5:
            await message.channel.send("Virhe: Väärä määrä parametreja. Komennolle `!autodelete aseta` täytyy antaa kolme parametria.")
            return

        # Check the parameter types
        try:
            channel_name, time_horizon_days, interval_hours = tokens[2], int(tokens[3]), int(tokens[4])
            if time_horizon_days < 1 or interval_hours < 1:
                raise ValueError("Time parameter not positive")
        except ValueError:
            await message.channel.send("Virhe: Vääränlaiset parametrit. Komennolle `!autodelete aseta` täytyy antaa kanavan nimi ja kaksi positiivista kokonaislukua.")
            return

        # Check that the channel exists
        if not (channel_name in [C.name for C in message.guild.channels]):
            await message.channel.send("Virhe: Kanavaa #{} ei ole olemassa tai minulla ei ole oikeuksia siihen.".format(channel_name))
            return

        # Run the command
        global_config["instances"][message.guild.id]["autodelete_channels"] = mybot.set_autodel(channel_name, interval_hours*60, time_horizon_days*60*24)

        # Print the new settings to channel
        await message.channel.send(mybot.get_settings_string())

        # Update config file
        with open(yaml_filename, 'w') as outfile:
          yaml.dump(global_config, outfile, default_flow_style=False)
        print("Updated config file", yaml_filename)

client.run(global_config["token"])
