import sys, os
if 'TRAVIS' in os.environ:
	sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


import unittest
from typeWorld.client import APIClient, JSON, AppKitNSUserDefaults
import tempfile, os, traceback
tempFolder = tempfile.mkdtemp()
from typeWorld.api import *


prefs = JSON(os.path.join(tempFolder, 'preferences.json'))
client = APIClient(preferences = prefs)

prefs2 = JSON(os.path.join(tempFolder, 'preferences2.json'))
client2 = APIClient(preferences = prefs)

freeSubscription = 'typeworld://json+https//typeworldserver.com/api/q8JZfYn9olyUvcCOiqHq/'
protectedSubscription = 'typeworld://json+https//s9lWvayTEOaB9eIIMA67:bN0QnnNsaE4LfHlOMGkm@typeworldserver.com/api/q8JZfYn9olyUvcCOiqHq/'
testUser = ('736b524a-cf24-11e9-9f62-901b0ecbcc7a', 'AApCEfatt6vE5H4m0pevPsQA9P7fYG8Q1uhsNFYV')


class TestStringMethods(unittest.TestCase):


	def test_api(self):



		# InstallableFonts

		# Root of API
		api = APIRoot()
		api.name.en = 'Font Publisher'
		api.canonicalURL = 'http://fontpublisher.com/api/'
		api.adminEmail = 'admin@fontpublisher.com'
		api.supportedCommands = [x['keyword'] for x in COMMANDS] # this API supports all commands
		print(api)

		# Response for 'availableFonts' command
		response = Response()
		response.command = 'installableFonts'
		responseCommand = InstallableFontsResponse()
		responseCommand.type = 'success'
		response.installableFonts = responseCommand
		api.response = response
		print(response)
		print(responseCommand)

		# Add designer to root of response
		designer = Designer()
		designer.keyword = 'max'
		designer.name.en = 'Max Mustermann'
		responseCommand.designers.append(designer)
		print(designer)
		assert designer.parent == responseCommand

		responseCommand.designers.extend([designer])
		responseCommand.designers.remove(responseCommand.designers[-1])
		assert len(responseCommand.designers) == 1
		print(responseCommand.designers)

		# Add foundry to root of response
		foundry = Foundry()
		foundry.uniqueID = 'yanone'
		foundry.name.en = 'Awesome Fonts'
		foundry.name.de = 'Tolle Schriften'
		foundry.website = 'https://awesomefonts.com'
		responseCommand.foundries.append(foundry)
		print(foundry)
		print(foundry.name.getTextAndLocale('en'))
		print(foundry.name.getTextAndLocale('ar'))
		assert foundry.name.getTextAndLocale('en') == ('Awesome Fonts', 'en')
		assert foundry.name.getTextAndLocale(['en']) == ('Awesome Fonts', 'en')
		assert foundry.name.getTextAndLocale('de') == ('Tolle Schriften', 'de')
		assert foundry.name.getTextAndLocale(['de']) == ('Tolle Schriften', 'de')

		# Add license to foundry
		license = LicenseDefinition()
		license.keyword = 'awesomeFontsEULA'
		license.name.en = 'Awesome Fonts Desktop EULA'
		license.URL = 'https://awesomefonts.com/EULA/'
		foundry.licenses.append(license)
		print(license)
		assert license.parent == foundry

		# Add font family to foundry
		family = Family()
		family.uniqueID = 'yanone-AwesomeSans'
		family.name.en = 'Awesome Sans'
		family.designers.append('max')
		foundry.families.append(family)
		print(family)
		assert family.parent == foundry

		# Add version to font
		version = Version()
		version.number = 0.1
		family.versions.append(version)
		print(version)
		assert version.isFontSpecific() == False
		assert version.parent == family
		assert type(family.getDesigners()) == list
		assert type(family.getAllDesigners()) == list

		# Add font to family
		font = Font()
		font.uniqueID = 'yanone-NonameSans-Regular'
		font.name.en = 'Regular'
		font.postScriptName = 'AwesomeSans-Regular'
		font.purpose = 'desktop'
		print(font.format)
		print(font.validate())
		font.format = 'otf'
		font.designers.append('max')
		font.dateAddedForUser = '2018-04-01'
		family.fonts.append(font)
		print(font.getDesigners())
		usedLicense = LicenseUsage()
		usedLicense.keyword = 'awesomeFontsEULA'
		font.usedLicenses.append(usedLicense)
		print(usedLicense)
		print(font)
		assert usedLicense.parent == font


		# Add font to family
		font = Font()
		font.uniqueID = 'yanone-NonameSans-Bold'
		font.name.en = 'Regular'
		font.postScriptName = 'AwesomeSans-Bold'
		font.purpose = 'desktop'
		font.format = 'otf'
		usedLicense = LicenseUsage()
		usedLicense.keyword = 'awesomeFontsEULA'
		font.usedLicenses.append(usedLicense)
		family.fonts.append(font)
		assert usedLicense.parent == font
		assert font.parent == family

		# Add version to font
		version = Version()
		version.number = 0.2
		font.versions.append(version)
		print(version)
		assert version.isFontSpecific() == True
		assert version.parent == font

		assert len(font.getVersions()) == 2
		assert type(font.getDesigners()) == list

		# Output API response as JSON, includes validation
		json = api.dumpJSON()

		# Let’s see it
		print(json)

		# Load a second API instance from that JSON
		api2 = APIRoot()
		api2.loadJSON(json)

		# Let’s see if they are identical
		assert api.sameContent(api2) == True

		api.validate()


		# Check for errors

		try: 
			api.licenseIdentifier = 'abc'
		except ValueError:
		 	pass
		api.licenseIdentifier = 'CC-BY-NC-ND-4.0'

		try: 
			font.format = 'abc'
		except ValueError:
			pass


		try: 
			font.uniqueID = 'a' * 500
		except ValueError:
			pass


		font.uniqueID = 'a' * 255
		information, warnings, critical = api.validate()
		assert critical != []

		font.uniqueID = 'abc:def'
		information, warnings, critical = api.validate()
		assert critical != []

		# Back to normal
		font.uniqueID = 'yanone-NonameSans-Bold'
		information, warnings, critical = api.validate()
		assert critical == []


		try: 
			response.command = 'abc'
		except ValueError:
			pass
		response.command = 'installableFonts'

		try:
			# Too long name
			foundry.name.en = 'abc' * 1000
			# Output API response as JSON, includes validation
			json = api.dumpJSON()
		except ValueError:
			pass
		foundry.name.en = 'abc'
		


		# InstallFont


		# Root of API
		api2 = APIRoot()
		api2.name.en = 'Font Publisher'
		api2.canonicalURL = 'https://fontpublisher.com/api/'
		api2.adminEmail = 'admin@fontpublisher.com'
		api2.supportedCommands = [x['keyword'] for x in COMMANDS] # this API supports all commands
		print(api2)

		# Response for 'availableFonts' command
		response = Response()
		response.command = 'installFont'
		responseCommand = InstallFontResponse()
		responseCommand.type = 'success'
		response.installFont = responseCommand
		api2.response = response
		print(response)
		print(responseCommand)

		responseCommand.font = b'ABC'
		responseCommand.encoding = 'base64'

		# Output API response as JSON, includes validation
		json = api2.dumpJSON()





		# UninstallFont


		# Root of API
		api3 = APIRoot()
		api3.name.en = 'Font Publisher'
		api3.canonicalURL = 'https://fontpublisher.com/api/'
		api3.adminEmail = 'admin@fontpublisher.com'
		api3.supportedCommands = [x['keyword'] for x in COMMANDS] # this API supports all commands
		print(api3)

		# Response for 'availableFonts' command
		response = Response()
		response.command = 'uninstallFont'
		responseCommand = UninstallFontResponse()
		responseCommand.type = 'success'
		response.uninstallFont = responseCommand
		api3.response = response
		print(response)
		print(responseCommand)

		# Output API response as JSON, includes validation
		json = api3.dumpJSON()



		# Docu



		# Docu
		docu = api.docu()




		# Data types
		try:
			BooleanDataType().put('abc')
		except ValueError:
			pass

		try:
			IntegerDataType().put('abc')
		except ValueError:
			pass

		try:
			FloatDataType().put('abc')
		except ValueError:
			pass

		try:
			FontEncodingDataType().put('abc')
		except ValueError:
			pass

		try:
			VersionDataType().put('0.1.2.3')
		except ValueError:
			pass

		try:
			WebURLDataType().put('yanone.de')
		except ValueError:
			pass

		try:
			EmailDataType().put('post@yanone')
		except ValueError:
			pass

		try:
			HexColorDataType().put('ABCDEF') # pass
			HexColorDataType().put('ABCDEX') # error
		except ValueError:
			pass

		try:
			HexColorDataType().put('012345678')
		except ValueError:
			pass

		try:
			DateDataType().put('2018-02-28') # pass
			DateDataType().put('2018-02-30') # error
		except ValueError:
			pass


		try:
			font.type = 'abc'
		except:
			pass

		# __repr__
		print(font.uniqueID)

		l = FontListProxy()
		print(l)
		l.append(Font())
		l[0] = Font()

		l = font.nonListProxyBasedKeys()

		font.doesntHaveThisAttribute = 'a'
		print(font.doesntHaveThisAttribute)
		try:
			print(font.doesntHaveThatAttribute)
		except:
			pass


		font.postScriptName = ''

		font.name = MultiLanguageText()
		font.name.en = None
		print(font.name.parent)
		try:
			print(api.validate())
		except:
			pass


		usedLicense = LicenseUsage()
		usedLicense.keyword = 'awesomeFontsEULAAAAA'
		font.usedLicenses.append(usedLicense)
		try:
			print(api.validate())
		except:
			pass


		font.versions = []
		font.parent.versions = []
		try:
			print(api.validate())
		except:
			pass


		font.designers.append('maxx')
		try:
			print(api.validate())
		except:
			pass






	def test_normalSubscription(self):


		## Test a simple subscription of free fonts


		success, message, publisher, subscription = client.addSubscription(freeSubscription)
		print(success, message)

		self.assertEqual(success, True)
		self.assertEqual(publisher.canonicalURL, 'https://typeworldserver.com/api/q8JZfYn9olyUvcCOiqHq/')
		self.assertEqual(len(publisher.subscriptions()), 1)
		self.assertEqual(len(publisher.subscriptions()[-1].protocol.installableFontsCommand().foundries), 1)
		self.assertEqual(publisher.subscriptions()[-1].protocol.installableFontsCommand().foundries[0].name.getTextAndLocale(), ('Test Foundry', 'en'))

		for subscription in publisher.subscriptions():
			subscription.delete()


		# Protected subscription, installation on first machine

		client.linkUser(*testUser)

		success, message, publisher, subscription = client.addSubscription(protectedSubscription)
		print(success, message)

		self.assertEqual(success, True)
		self.assertEqual(len(publisher.subscriptions()), 1)
		self.assertEqual(len(publisher.subscriptions()[-1].protocol.installableFontsCommand().foundries), 1)

		client.downloadSubscriptions()

		client.publishers()[0].update()

		# Install Font
		font = client.publishers()[0].subscriptions()[-1].protocol.installableFontsCommand().foundries[0].families[0].fonts[0]
		self.assertEqual(client.publishers()[0].subscriptions()[-1].installFont(font.uniqueID, font.getVersions()[-1].number), (False, ['#(response.termsOfServiceNotAccepted)', '#(response.termsOfServiceNotAccepted.headline)']))
		client.publishers()[0].subscriptions()[-1].set('acceptedTermsOfService', True)
		self.assertEqual(client.publishers()[0].subscriptions()[-1].installFont(font.uniqueID, font.getVersions()[-1].number), (False, ['#(response.revealedUserIdentityRequired)', '#(response.revealedUserIdentityRequired.headline)']))
		client.publishers()[0].subscriptions()[-1].set('revealIdentity', True)
		self.assertEqual(client.publishers()[0].subscriptions()[-1].installFont(font.uniqueID, font.getVersions()[-1].number), (True, None))


		# Protected subscription, installation on second machine
		# Supposed to reject because seats are limited to 1

		client2.linkUser(*testUser)
		success, message, publisher, subscription = client2.addSubscription(protectedSubscription)
		print(success, message)

		font2 = client2.publishers()[0].subscriptions()[-1].protocol.installableFontsCommand().foundries[0].families[0].fonts[0]

		# Two versions available
		self.assertEqual(len(client2.publishers()[0].subscriptions()[-1].installFont(font2.uniqueID, font2.getVersions())), 2)

		client2.publishers()[0].subscriptions()[-1].set('acceptedTermsOfService', True)
		client2.publishers()[0].subscriptions()[-1].set('revealIdentity', True)
		self.assertEqual(client2.publishers()[0].subscriptions()[-1].installFont(font2.uniqueID, font2.getVersions()[-1].number), (False, ['#(response.seatAllowanceReached)', '#(response.seatAllowanceReached.headline)']))

		# Uninstall font on first client
		result = client.publishers()[0].subscriptions()[-1].removeFont(font.uniqueID)
		print(result)
		self.assertEqual(result, (True, None))

		# Uninstall font on second client, must fail because deleting same font file
		result = client2.publishers()[0].subscriptions()[-1].removeFont(font2.uniqueID)
		print(result)
		self.assertEqual(result, (False, 'Font path couldn’t be determined'))

		# Try again on second client
		self.assertEqual(client2.publishers()[0].subscriptions()[-1].installFont(font2.uniqueID, font2.getVersions()[-1].number), (True, None))

		# Uninstall font on second client
		result = client2.publishers()[0].subscriptions()[-1].removeFont(font2.uniqueID)
		print(result)
		self.assertEqual(result, (True, None))

		# Install older version on second client
		self.assertEqual(client2.publishers()[0].subscriptions()[-1].installFont(font2.uniqueID, font2.getVersions()[0].number), (True, None))

		# One font must be outdated
		self.assertEqual(client2.amountOutdatedFonts(), 1)

		# Uninstall font on second client
		result = client2.publishers()[0].subscriptions()[-1].removeFont(font2.uniqueID)
		print(result)
		self.assertEqual(result, (True, None))



	def test_takedown(self):

		for publisher in client.publishers():
			for subscription in publisher.subscriptions():
				subscription.delete()

		for publisher in client2.publishers():
			for subscription in publisher.subscriptions():
				subscription.delete()

		client.unlinkUser()
		client2.unlinkUser()

if __name__ == '__main__':
	unittest.main()


 # Local
if not 'TRAVIS' in os.environ:
#	os.remove(prefFile)
	os.rmdir(tempFolder)
