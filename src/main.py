import os
import sys
import re
import requests
import praw
import discord_logging
import bs4
import traceback
import time

# this is a logging setup library. But we only want to print out to the console, so we tell it to skip logging to a file
log = discord_logging.init_logging(folder=None)

from saucenao import SauceNAO


def load_environment():
	# rather than hard coding the credentials in the code, we'll use heroku's environment variables
	variable_names = ['username', 'password', 'client_id', 'client_secret', 'saucenao_key']
	success = True
	variables = {}
	for name in variable_names:
		value = os.getenv(name)
		if value is None:
			log.warning(f"`{name}` is missing from environment")
			success = False
		else:
			variables[name] = value
	if success:
		return variables
	else:
		return None


def init_praw(env_variables):
	# create the reddit instance and try to login
	reddit_instance = praw.Reddit(
		username=env_variables['username'],
		password=env_variables['password'],
		client_id=env_variables['client_id'],
		client_secret=env_variables['client_secret'],
		user_agent="HentaiSauce_Bot")

	try:
		logged_in_name = reddit_instance.user.me().name
		log.info(f"Logged into reddit as u/{logged_in_name}")
		return reddit_instance
	except Exception as err:
		log.warning(f"Couldn't log into reddit: {err}")
		log.warning(traceback.format_exc())
		return None


def build_multireddits():
	# you can load multiple subreddits by joining them with +, but there's actually a limit of how many you can do
	# this with. The limit is pretty big, but ~500 subreddits is pushing it. Safer to split into several requests
	# so we don't run into problems if the bot keeps growing

	subreddit_names = []
	for subreddit_name in reddit.user.me().moderated():
		subreddit_names.append(subreddit_name.display_name)
	log.info(f"Loaded {len(subreddit_names)} subreddits")

	multireddits = []
	multireddit = []
	for subreddit_name in subreddit_names:
		if len(multireddit) >= 200:
			multireddits.append('+'.join(multireddit))
			multireddit = []
		multireddit.append(subreddit_name)
	if len(multireddit) > 0:
		multireddits.append('+'.join(multireddit))

	log.info(f"Split into {len(multireddits)} multireddits")
	return multireddits


def get_submissions_from_multireddit(reddit, multireddit, submissions):
	count_skipped = 0
	try:
		# we want to get a whole bunch of old submissions in case the bot hasn't been running for a while, but
		# we also don't want to waste time getting all of them if we've already processed them. So when we process
		# a submission, we'll save it. Then next time we check if it's saved, and skip it if it is. When we're
		# loading submissions, if we get 10 that are saved, we can assume we've already processed all the older
		# ones and stop looking
		for submission in reddit.subreddit(multireddit).new(limit=100):
			if submission.saved:
				count_skipped += 1
			else:
				submissions.append(submission)
			if count_skipped >= 10:
				break
	except Exception as err:
		log.warning(f"Exception while getting submissions from multireddit: {err}")
		log.warning(traceback.format_exc())


def parse_saucenao(page_html, image_url):
	# take a saucenao page and extract all the information from it
	if page_html is None:
		return None

	txt = page_html.split('Low similarity results')[0]
	soup = bs4.BeautifulSoup(txt, 'html.parser')

	# we use an object here rather than a dictionary since it makes everything look much cleaner
	saucenao = SauceNAO()
	saucenao.saucenao_link = f"http://saucenao.com/search.php?db=999&url={image_url}"
	soup_str = str(soup)

	creator = re.search(r"Creator: <\/strong>([\w\d\s\-_.*()\[\]]*)<br\/>", soup_str)
	if creator:
		saucenao.creator = creator.group(1)
	material = re.search(r"Material: <\/strong>([\w\d\s\-_.*()\[\]]*)<br\/>", soup_str)
	if material:
		saucenao.material = material.group(1)
	author = re.search(r'Author: <\/strong><[\w\s\d="\-_\.\/\?:]*>([\w\d\s\-_.*()\[\]]*)<\/a>', soup_str)
	if author:
		saucenao.author = author.group(1)
	member = re.search(r'Member: <\/strong><[\w\s\d="\-_\.\/\?:]*>([\w\d\s\-_.*()\[\]]*)<\/a>', soup_str)
	if member:
		saucenao.member = member.group(1)

	for link in soup.find_all('a'):
		pg = link.get('href')
		if re.search(r"[\w]+\.deviantart\.com", pg):
			saucenao.update_if_none('deviantart_art', pg)
		if re.search(r"deviantart\.com\/view\/", pg):
			saucenao.update_if_none('deviantart_src', pg)
		if re.search(r"pixiv\.net\/member\.", pg):
			saucenao.update_if_none('pixev_art', pg)
		if re.search(r"pixiv\.net\/member_illust", pg):
			saucenao.update_if_none('pixev_src', pg)
		if re.search(r"gelbooru\.com\/index\.php\?page", pg):
			saucenao.update_if_none('gelbooru', pg)
		if re.search(r"danbooru\.donmai\.us\/post\/", pg):
			saucenao.update_if_none('danbooru', pg)
		if re.search(r"chan\.sankakucomplex\.com\/post", pg):
			saucenao.update_if_none('sankaku', pg)

	return saucenao


def get_saucenao_page(image_url, saucenao_key):
	try:
		resp = requests.get(f"http://saucenao.com/search.php?db=999&api_key={saucenao_key}&url={image_url}")
		return resp.text
	except Exception as err:
		log.warning(f"Failed to load saucenao page: {err}")
		log.warning(traceback.format_exc())
		return None


def build_comment(saucenao):
	# take the saucenao fields and build out the comment to respond with
	# rather than just appending strings one after another, we make a list of all of them and put them
	# together at the end, it's more efficient
	if saucenao is None:
		return None

	bldr = []
	if saucenao.creator is not None or saucenao.member is not None or saucenao.author is not None:
		bldr.append('**Creator:** ')
		if saucenao.creator is not None:
			bldr.append(saucenao.creator.title())
			bldr.append(' | ')
		if saucenao.member is not None:
			bldr.append(saucenao.member)
			if saucenao.pixev_art is not None:
				bldr.append(' [^({{on Pixiv}})](')
				bldr.append(saucenao.pixev_art)
				bldr.append(')')
			bldr.append(' | ')
		if saucenao.author is not None and saucenao.member is None:
			bldr.append(saucenao.author)
			if saucenao.deviantart_art is not None:
				bldr.append(' [^({{on DeviantArt}})](')
				bldr.append(saucenao.deviantart_art)
				bldr.append(')')
			bldr.append(' | ')
		bldr.append('\n\n')

	if saucenao.material is not None:
		bldr.append('**Material:** ')
		bldr.append(saucenao.material.title())
		if saucenao.material != 'original':
			bldr.append(' [^({{Google it!}})](http://www.google.com/search?q=')
			bldr.append(saucenao.material.replace(' ', '+'))
			bldr.append(') [^({{Hentify it!}})](https://gelbooru.com/index.php?page=post&s=list&tags=')
			bldr.append(saucenao.material.replace(' ', '_'))
			bldr.append(')')
		bldr.append('\n\n')

	if saucenao.pixev_src is not None or saucenao.gelbooru is not None or saucenao.danbooru is not None or saucenao.sankaku is not None or saucenao.deviantart_src is not None:
		bldr.append('**Image links:** ')
		if saucenao.pixev_src is not None:
			bldr.append('[Pixiv](')
			bldr.append(saucenao.pixev_src)
			bldr.append(') | ')
		if saucenao.gelbooru is not None:
			bldr.append('[Gelbooru](')
			bldr.append(saucenao.gelbooru)
			bldr.append(') | ')
		if saucenao.danbooru is not None:
			bldr.append('[Danbooru](')
			bldr.append(saucenao.danbooru)
			bldr.append(') | ')
		if saucenao.sankaku is not None:
			bldr.append('[Sankaku](')
			bldr.append(saucenao.sankaku)
			bldr.append(') | ')
		if saucenao.deviantart_src is not None:
			bldr.append('[DeviantArt](')
			bldr.append(saucenao.deviantart_src)
			bldr.append(') | ')
		bldr.append('\n\n')

	# Handle no results
	if len(bldr) == 0:
		return None

	bldr.append("---\n | ")
	bldr.append("**Support this service on [Patreon](https://www.patreon.com/r_Hentai)** | \n\n")
	bldr.append("[View full results](")
	bldr.append(saucenao.saucenao_link)
	bldr.append(") | **Created for r/Hentai** | ")
	bldr.append("**Powered by [SauceNAO](https://saucenao.com/)**")

	return ''.join(bldr)


def not_found_text():
	return \
		'Submission is not an image or sauce could not be found!\n\n---\n^| ' \
		'^Created for r/Hentai [(Questions?)](https://reddit.com/user/Kicken)'


if __name__ == '__main__':
	log.info("Starting up...")

	env_values = load_environment()
	if env_values is None:
		sys.exit(1)

	reddit = init_praw(env_values)
	if reddit is None:
		sys.exit(1)

	log.info("Loading list of moderated subs...")
	multireddits = build_multireddits()

	log.info(f"Finished start up, checking submissions and messages")
	# just keep looping forever
	while True:
		try:
			submissions = []
			for multireddit in multireddits:
				get_submissions_from_multireddit(reddit, multireddit, submissions)

			if len(submissions) > 0:
				log.debug(f"Processing {len(submissions)} submissions")

				for submission in submissions:
					image_url = None
					comment_reply = None
					# figure out if this post is an image we can process
					if submission.url[-4:] == '.jpg' or submission.url[-4:] == '.png':
						image_url = submission.url
					elif(submission.url[8:14] == 'imgur.' and submission.url[17:20] != '/a/') or \
							(submission.url[8:16] == 'i.imgur.' and submission.url[19:22] != '/a/'):
						image_url = submission.url + '.jpg'

					# if we don't have a url we can lookup, reply with the not found comment and automatically remove it
					if image_url is None:
						log.info(
							f"Post {submission.id} in r/{submission.subreddit.display_name} didn't have a url to lookup")
						result_comment = submission.reply(not_found_text())
						result_comment.mod.remove()
					else:
						log.info(
							f"Processing post {submission.id} in r/{submission.subreddit.display_name} with url {image_url}")
						# get the saucenao page html
						saucenao_page = get_saucenao_page(image_url, env_values['saucenao_key'])
						# then parse it into an object
						saucenao = parse_saucenao(saucenao_page, image_url)
						# and finally try building the result comment
						comment_reply = build_comment(saucenao)

						# if we didn't find a source, message the post author and post the comment
						if comment_reply is None:
							log.info(f"Couldn't find a source, messaging author u/{submission.author.name}")
							submission.author.message(
								"Sauce not found!",
								f"I couldn't find the source for your [recent submission]({submission.permalink}). "
								f"Please consider putting it in the comments yourself.")
							result_comment = submission.reply(not_found_text())
							result_comment.mod.remove()
						else:
							log.info(f"Source found, replying with comment")
							result_comment = submission.reply(comment_reply)
							result_comment.mod.distinguish(sticky=True)

					submission.save()

			# check messages for mod invites
			for message in reddit.inbox.unread():
				rebuild = False
				if "invitation to moderate /r/" in message.subject:
					try:
						log.info(f"Accepting mod invite for r/{message.subreddit.display_name}")
						message.subreddit.mod.accept_invite()
						rebuild = True
					except Exception as err:
						log.warning(f"Error accepting mod invite: {err}")
						log.warning(traceback.format_exc())

				if "has been removed as a moderator from" in message.subject:
					log.info(f"Removed as mod from r/{message.subreddit.display_name}")
					rebuild = True

				if rebuild:
					multireddits = build_multireddits()
				elif message.author is not None:
					log.info(f"Got a message from u/{message.author.name}, but it's not a mod invite. {message.id}")
				message.mark_read()

			time.sleep(15)

		except Exception as err:
			log.warning(f"Caught top level error: {err}")
			log.warning(traceback.format_exc())
