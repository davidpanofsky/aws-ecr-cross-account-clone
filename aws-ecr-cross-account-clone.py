#!/usr/bin/python3
####################################################################
#
# AWS ECR smart synchronization tool
#
# (C) Dmytro Fadyeyenko
# GitHub: https://github.com/dfad1ripe/aws-ecr-cross-account-clone
#
####################################################################

import argparse
from datetime import date
import json
import re
import subprocess
import threading
import boto3

# Default values
#
# Debug mode output is allowed - not for production usage
DEBUG      = False
DEBUG_AUTH = False
INFO       = True

# Exit codes
errInvalidArgument  = 1
errInvalidFile      = 2
errShell            = 11
errAWS              = 21
errDocker           = 22


# Debug level printing
def debug(message):
  if DEBUG:
    print(message)

    
# Info level printing
def info(message):
  if INFO:
    print(message)

    
# Validating a value against regular expression
def validate(var, regex, errMsg, exitCode):
  debug('Validating ' + var + ' against ' + regex)
  try:
    pattern = re.compile(regex)
    if re.fullmatch(pattern, var):
      debug('Validation successfull')
    else:
      print(errMsg)
      exit(exitCode)
  except ValueError as err:
    print(err)



# Read repositories from AWS region
def getRepos(session):
  debug('Retrieving repos: ' + session.profile_name + ':' + session.region_name)
  client = session.client('ecr')
  #cmd = 'aws ecr describe-repositories --profile ' + session.profile_name + ' --region ' + session.region_name
  response = client.describe_repositories()

  # Return .repositories[] property
  return j['repositories']
  

# Get list of images for AWS ECR repo
def getRepoImages(profile, region, repositoryName):
  info('Retrieving images for repository: ' + profile + ':' + region + ':' + repositoryName)
  cmd = 'aws ecr describe-images --profile ' + profile + ' --region ' + region + ' --repository-name ' + repositoryName
  debug('Running command: ' + cmd)

  p = subprocess.Popen(cmd.split(),
                       stdout = subprocess.PIPE,
                       stderr = subprocess.PIPE,
                       #stdin  = subprocess.PIPE,
                       universal_newlines = True)
  stdout, stderr = p.communicate()

  if p.returncode > 0:
    # Shell error happened
    print(stderr)
    exit(errAWS)
  else:
    debug(stdout)
  
  # Convert JSON text to a list
  j = json.loads(stdout)
  
  # Return .imageDetails[] property
  return j['imageDetails']  


# Create repository
# arguments:
#   - AWS profile
#   - AWS region
#   - Name of repository to create
#   = Whether to enable scan on push (boolean, default true)
# returns: nothing
def createRepo(profile, region, repositoryName, scanOnPush=True):
  debug('Creating repository: ' + profile + ':' + region + ':' + repositoryName)
  cmd = 'aws ecr create-repository --profile ' + profile + ' --region ' + region + ' --repository-name ' + repositoryName
  if scanOnPush:
    cmd = cmd + ' --image-scanning-configuration scanOnPush=true'
  debug('Running command: ' + cmd)
  p = subprocess.Popen(cmd.split(),
                       stdout = subprocess.PIPE,
                       stderr = subprocess.PIPE,
                       #stdin  = subprocess.PIPE,
                       universal_newlines = True)
  stdout, stderr = p.communicate()

  if p.returncode > 0:
    # Shell error happened
    print(stderr)
    exit(errAWS)
  else:
    debug(stdout)

  
# Calculate age of image, in calendar days
def imageAge(image):
  pushedAt = re.sub("T.*", "", str(image['imagePushedAt']))
  pushedDate = date.fromisoformat(pushedAt)
  return ((date.today() - pushedDate).days)

  
# Retrieve credentials for ECR repository  
def getECRCredentials(profile, region):
  info('Retrieving credentials for: ' + profile + ':' + region)
  cmd = 'aws ecr get-login-password --region ' + region + ' --profile ' + profile

  debug('Running command: ' + cmd)

  p = subprocess.Popen(cmd.split(),
                       stdout = subprocess.PIPE,
                       stderr = subprocess.PIPE,
                       #stdin  = subprocess.PIPE,
                       universal_newlines = True)
  stdout, stderr = p.communicate()

  if p.returncode > 0:
    # Shell error happened
    print(stderr)
    exit(errAWS)
  else:
    if DEBUG_AUTH:
      debug(stdout)
    else:
      debug('ECR authorization token was retrieved as <HIDDEN>')
    return stdout.rstrip()


# Multipurpose docker runner
# Allows to run `docker <command> <any arguments>`
# arguments:
#   - command for docker
#   - arguments for docker command
# returns subprocess stdout
def dockerRunner(command, arguments):
  cmd = 'docker ' + command + ' ' + arguments
  debug('Running command: ' + cmd)
  p = subprocess.Popen(cmd.split(),
                       stdout = subprocess.PIPE,
                       stderr = subprocess.PIPE,
                       #stdin  = subprocess.PIPE,
                       universal_newlines = True)
  stdout, stderr = p.communicate()

  if p.returncode > 0:
    # Shell error happened
    print(stderr)
    exit(errDocker)
  else:
    return stdout
  

# Docker login
# arguments:
#   - FQDN for ECR registry
#   - password
# returns: nothing, underlying docker runner exits on docker failure
def dockerLogin(FQDN, password):
  info('Docker login to: ' + FQDN)
  if DEBUG_AUTH:
    debug('  using password: ' + password)
  else:
    debug('  using password: <HIDDEN>')

  if DEBUG_AUTH:
    r = dockerRunner('login', '--username AWS --password ' + password + ' ' + FQDN)
  else:
    cmd = 'docker login --username AWS --password ' + password + ' ' + FQDN
    debug('Running command: docker login --username AWS --password <HIDDEN> ' + FQDN)
    p = subprocess.Popen(cmd.split(),
                         stdout = subprocess.PIPE,
                         stderr = subprocess.PIPE,
                         universal_newlines = True)
    stdout, stderr = p.communicate()

    if p.returncode > 0:
      # Shell error happened
      print(stderr)
      exit(errDocker)
    else:
      r = stdout
  
  print(r)

  
# Docker pull image
# arguments:
#   - full image name
# returns: nothing, underlying docker runner exits on docker failure
def dockerPull(imageName):
  info('Pulling image: ' + imageName)
  r = dockerRunner('pull', imageName)
  print(r)

    
# Docker tag image
# arguments:
#   - full image name
#   - new full image name
# returns: nothing, underlying docker runner exits on docker failure
def dockerTag(imageName, newImageName):
  info('Tagging image: ' + imageName + ' as ' + newImageName)
  r = dockerRunner('tag', imageName + ' ' + newImageName)
  print(r)
    
    
# Docker push image
# arguments:
#   - full image name
# returns: nothing, underlying docker runner exits on docker failure
def dockerPush(imageName):
  info('Pushing image: ' + imageName)
  cmd = 'docker push ' + imageName
  r = dockerRunner('push', imageName)
  print(r)


# Docker remove local image
# arguments:
#   - full image name
# returns: nothing, underlying docker runner exits on docker failure
def dockerRmi(imageName):
  info('Removing image: ' + imageName)
  cmd = 'docker rmi ' + imageName
  r = dockerRunner('rmi', imageName)
  print(r)

    
# Build ECR FQDN for profile
# arguments:
#   - AWS profile
#   - AWS region
# returns: FQDN for ECR in this profile and region
def buildFQDN(profile, region):
  info('Generating ECR FQDN for profile: ' + profile)
  cmd = 'aws ecr describe-registry --profile ' + profile

  debug('Running command: ' + cmd)

  p = subprocess.Popen(cmd.split(),
                       stdout = subprocess.PIPE,
                       stderr = subprocess.PIPE,
                       #stdin  = subprocess.PIPE,
                       universal_newlines = True)
  stdout, stderr = p.communicate()

  if p.returncode > 0:
    # Shell error happened
    print(stderr)
    exit(errAWS)
  else:
    debug(stdout)
    
  # Convert JSON text to a list
  j = json.loads(stdout)
  
  accountId = j['registryId']
  return str(accountId) + '.dkr.ecr.' + region + '.amazonaws.com'


# Check if a repository with given name exists in repository list
# arguments:
#   - list of repositories (generated from JSON returned by AWS)
#   - name of repository to check
# returns: boolean
def repoExists(repositoryList, repositoryName):
  exists = False
  for repo in repositoryList:
    if repo['repositoryName'] == repositoryName:
      debug('Repository ' + repositoryName + ' exists in the list')
      exists = True
      break
  if not exists:
      debug('Repository ' + repositoryName + ' does not exist in the list')

  return exists


# Describe image
# arguments:
#   - AWS profile
#   - AWS region
#   - Repository name
#   - Image tag
# returns: What AWS returns as JSON for the image, {} if does not exist
def describeImage(profile, region, repositoryName, tag):
  debug('Retrieving metadata for image: ' + profile + ':' + region + ', ' + repositoryName + ':' + tag)
  #cmd = 'aws ecr describe-images --profile ' + profile + ' --repository-name ' + repositoryName + ' --image-ids imageTag=' + tag
  cmd = 'aws ecr describe-images --profile ' + profile + ' --repository-name ' + repositoryName + ' --query "imageDetails[?contains(imageTags,`' + tag + '`)]"'
  debug('Running command: ' + cmd)

  p = subprocess.Popen(cmd.split(),
                       stdout = subprocess.PIPE,
                       stderr = subprocess.PIPE,
                       #stdin  = subprocess.PIPE,
                       universal_newlines = True)
  stdout, stderr = p.communicate()

  if p.returncode > 0:
    # Shell error happened
    print(stderr)
    exit(errAWS)
  else:
    debug(stdout)
    
  # Convert JSON text to a list
  #images = json.loads(stdout)['imageDetails']
  images = json.loads(stdout)
  if not images:
      return {}
  else:
    for image in images:
      if image['imageTags'][0] == tag:
        debug('Found the image:')
        debug(image)
        return image
    
    # If such image is not found
    return {}
  

  
####################
# MAIN PROCESS
#


####################
# PART 1. Read and process arguments.
#

# Read CLI arguments
parser = argparse.ArgumentParser(description='AWS ECR smart synchronization tool.\nSee https://github.com/dfad1ripe/aws-crossrepo for the details.')
parser.add_argument('src_profile', type=str, help='Source AWS profile, as defined in ~/.aws/config')
parser.add_argument('src_region', type=str, help='Source AWS region')
parser.add_argument('dst_profile', type=str, help='Destination AWS profile, as defined in ~/.aws/config')
parser.add_argument('dst_region', type=str, help='Destination AWS region')
parser.add_argument('--days', '-d', type=int, default=30, help='How recent images to synchronize, in calendar days')
parser.add_argument('--require-scan', '-s', type=bool, nargs='?', default=False, const=True, help='Clone only scanned images (default False)')
parser.add_argument('--verbose', '-v', type=bool, nargs='?', default=False, const=True, help='More verbosity (default False)')
parser.add_argument('--verbose-auth', '-vv', type=bool, nargs='?', default=False, const=True, help='Verbose authentication data (default False)')
# Mutually exclusive arguments --exclude-repos and --include-repos
bwListGroup = parser.add_mutually_exclusive_group()
bwListGroup.add_argument('--exclude-repos', type=str, nargs='?', help='Comma-separated list of repositories to exclude from cloning ("black list")')
bwListGroup.add_argument('--include-repos', type=str, nargs='?', help='Comma-separated list of repositories to include to cloning ("white list")')

args = parser.parse_args()

# Validating arguments
debug('Validating parameters')
validate(args.src_profile, "^[a-z0-9\-\_]+$", 'Invalid profile name: ' + args.src_profile, errInvalidArgument)
validate(args.src_region, "^[a-z0-9\-]+$", 'Invalid region name: ' + args.src_region, errInvalidArgument)
validate(args.dst_profile, "^[a-z0-9\-\_]+$", 'Invalid profile name: ' + args.dst_profile, errInvalidArgument)
validate(args.dst_region, "^[a-z0-9\-]+$", 'Invalid region name: ' + args.dst_region, errInvalidArgument)

if args.days < 1:
  print('Invalid --days value: should be 1 or more')
  exit(errInvalidArgument)

if args.verbose:
  DEBUG = True

if args.verbose_auth:
  DEBUG = True
  DEBUG_AUTH = True

  
debug('')

src_session = boto3.Session(region_name=args.src_region, profile_name=args.src_profile)
dst_session = boto3.Session(region_name=args.dst_region, profile_name=args.dst_profile)

####################
# PART 2. Read ECR data and decide what to copy.
#

# Get repository list for Source repo
info('Retrieving list of repositories in ' + args.src_profile + ':' + args.src_region)
repoListSrc = getRepos(src_session)
debug(repoListSrc)

# Get repository list for Destination repo
# We need this to know if we have to create a repo pefore pushing an image
info('Retrieving list of repositories in ' + args.dst_profile + ':' + args.dst_region)
repoListDst = getRepos(dst_session)
debug(repoListDst)
info('')

if args.exclude_repos:
  # No need to try-catch here, as it would convert any bad syntax to a string
  repoListExclude = args.exclude_repos.split(',')
  for repoExclude in repoListExclude:
    validate(repoExclude, "^[a-zA-Z0-9\-\_]+$", 'Invalid repository name: ' + repoExclude, errInvalidArgument)
    for index,repo in enumerate(repoListSrc):
      if repo['repositoryName'] == repoExclude:
        debug('Repository ' + repoExclude + ' was excluded from cloning')
        repoListSrc.pop(index)
    
  
if args.include_repos:
  repoWhiteListSrc = []
  # No need to try-catch here, as it would convert any bad syntax to a string
  repoListInclude = args.include_repos.split(',')
  for repoInclude in repoListInclude:
    validate(repoInclude, "^[a-zA-Z0-9\-\_]+$", 'Invalid repository name: ' + repoInclude, errInvalidArgument)
    for index,repo in enumerate(repoListSrc):
      if repo['repositoryName'] == repoInclude:
        debug('Repository ' + repo['repositoryName'] + ' is included to cloning')
        repoWhiteListSrc.append(repo)
      else:
        debug('Repository ' + repo['repositoryName'] + ' was excluded from cloning')
  repoListSrc = repoWhiteListSrc


info('Retrieving list of images')
imagesToSync = []

for repo in repoListSrc:
  images = getRepoImages(args.src_profile, args.src_region, repo['repositoryName'])
  if len(images) == 0:
    info('  Repository is empty, skipping')
  else:
    for image in images:
    
      # Some images might have no tags
      try:
        tag = image['imageTags'][0]
      except (NameError, KeyError) as e:
        info('  Found image: ' + image['repositoryName'] + ':' + image['imagePushedAt'])
        info('    Image is not tagged, skipping')
        continue
        
      info('  Found image: ' + image['repositoryName'] + ':' + tag)

      # Is image too old to be cloned?
      age = imageAge(image)
      if age > args.days:
        info('    Image is ' + str(age) + ' day(s) old, skipping')
        continue
      else:
        debug('    Image is ' + str(age) + ' day(s) old')
      
      # If we requree an image to be scanned, is it?
      if args.require_scan:
        try:
          scanStatus = image['imageScanStatus']['status']
        except (NameError, KeyError) as e:
          info('    Image is not scanned, skipping')
          continue
        info('    Image is scanned')


      imagesToSync.append(image)


info('')

# If there is nothing to sync - report and exit

if len(imagesToSync) == 0:
  print('No images satisfy the given rules. Nothing to synchronize.')
  exit(0)

info('Number of images to synchronize: ' + str(len(imagesToSync)))
for image in imagesToSync:
  try:
    tag = image['imageTags'][0]
  except (NameError, KeyError) as e:
    info('  ' + image['repositoryName'] + ':' + image['imagePushedAt'])
  info('  ' + image['repositoryName'] + ':' + tag)

info('')

      
####################
# PART 3. Create missed repositories
#

# Create repositories that exist in Source and don't exist in Destination
reposToCreate = []
for image in imagesToSync:
  repositoryName = image['repositoryName']
  if repoExists(repoListDst, repositoryName):
    continue
  else:
    if repositoryName not in reposToCreate:
      reposToCreate.append(repositoryName)

if len(reposToCreate) > 0:
  info('The following repositories are missed at destination and will be created:')
  info(reposToCreate)
  info('')
  reposCreated = 0

  # Defining thread class
  class repoCreateThread(threading.Thread):
    def __init__(self, name, profile, region, repositoryName):
      threading.Thread.__init__(self)
      self.name = name
      self.profile = profile
      self.region = region
      self.repositoryName = repositoryName
    def run(self):
      global reposCreated
      debug('Starting thread: ' + self.name)
      createRepo(self.profile, self.region, self.repositoryName)
      reposCreated = reposCreated + 1
      info('  Repository ' + self.repositoryName + ' was created at ' + self.profile + ':' + self.region)
      debug('Exiting thread ' + self.name)


  # Running threads to create missed repositories
  threads = []
  for repo in reposToCreate:
    debug('Creating repository ' + repo + ' at ' + args.dst_profile + ':' + args.dst_region)
    repoCreate = repoCreateThread('creating repository ' + repo + ' at ' + args.dst_profile + ':' + args.dst_region,
                                  args.dst_profile,
                                  args.dst_region,
                                  repo)
    repoCreate.start()
    threads.append(repoCreate)

  # Waiting for all threads to complete
  for t in threads:
    t.join()
  debug('Multithreading part complete')

  # Check if all missed repositories were created successfully
  info('Successfuly created ' + str(reposCreated) + ' repositories of ' + str(len(reposToCreate)))
  if reposCreated < len(reposToCreate):
    print('Could not create all repositories. Please review the messages below and fix the error.')
    exit(errAWS)
  info('')

  
####################
# PART 4. Docker login to both repositories
#

# Build FQDN for repositories
fqdnSrc = re.sub("\/.*", "", repoListSrc[0]['repositoryUri'])
fqdnDst = buildFQDN(args.dst_profile, args.dst_region)

# Multithreading execution of docker login
#
# Initial structures
threads = []
threadsLogged = 0

# Defining thread class
class loginThread(threading.Thread):
  def __init__(self, name, profile, region, FQDN):
    threading.Thread.__init__(self)
    self.name = name
    self.profile = profile
    self.region = region
    self.FQDN = FQDN
  def run(self):
    global threadsLogged
    debug('Starting thread: ' + self.name)
    self.creds = getECRCredentials(self.profile, self.region)
    dockerLogin(self.FQDN, self.creds)
    threadsLogged = threadsLogged + 1
    debug('Exiting thread ' + self.name)

# Defining and running threads    
loginThreadSrc = loginThread('login thread for source repository',
                             args.src_profile,
                             args.src_region,
                             fqdnSrc)
loginThreadSrc.start()
threads.append(loginThreadSrc)

loginThreadDst = loginThread('login thread for destination repository',
                             args.dst_profile,
                             args.dst_region,
                             fqdnDst)
loginThreadDst.start()
threads.append(loginThreadDst)

# Waiting for all threads to complete
for t in threads:
    t.join()
debug('Multithreading part complete')

# Check if docker login was successful for both repositories
print('Successful login happened in ' + str(threadsLogged) + ' threads of 2')
if threadsLogged < 2:
  print('Docker was not able to login. Please review the messages below and fix the error.')
  exit(errDocker)


####################
# PART 5. Cloning images with docker
#

imagesToSyncFinal = []
for srcImage in imagesToSync:
  shouldBeCopied = False
  # Checking if sush image exists at destination
  info('Checking if the image ' + srcImage['repositoryName'] + ':' + srcImage['imageTags'][0] + ' exists at destination and has same checksum')
  dstImage = describeImage(args.dst_profile, args.dst_region, srcImage['repositoryName'], srcImage['imageTags'][0])
  
  try:
    print(srcImage)
    srcDigest = srcImage['imageDigest']
    dstDigest = dstImage['imageDigest']
    if srcDigest != dstDigest:
      shouldBeCopied = True
  except KeyError:
    # This happens when there is no dstImage['imageDigest'], meaning no such image
    shouldBeCopied = True
  
  if shouldBeCopied:
    info('  Image does not exist, or has different checksum, and should be copied')
    imagesToSyncFinal.append(srcImage)
  else:
    info('  Image exists and has the same checksum, skipping')
info('')
imagesToSync = imagesToSyncFinal

imagesPushed = 0
imageNamesPushed = []

# Defining thread class
class pushPullThread(threading.Thread):
  def __init__(self, name, imageName):
    threading.Thread.__init__(self)
    self.name = name
    self.imageName = imageName
  def run(self):
    global fqdnSrc
    global fqdnDst
    global imagesPushed
    debug('Starting thread: ' + self.name)
    dockerPull(fqdnSrc + '/' + self.imageName)
    dockerTag(fqdnSrc + '/' + self.imageName, fqdnDst + '/' + self.imageName)
    dockerPush(fqdnDst + '/' + self.imageName)
    imagesPushed = imagesPushed + 1
    imageNamesPushed.append(self.imageName)
    dockerRmi(fqdnSrc + '/' + self.imageName)
    dockerRmi(fqdnDst + '/' + self.imageName)
    debug('Exiting thread ' + self.name)


# Defining and running threads
threads = []
for image in imagesToSync:
  imageName = image['repositoryName'] + ':' + image['imageTags'][0]
  pushPullRunner = pushPullThread('push-pull thread for image ' + imageName, imageName)
  pushPullRunner.start()
  threads.append(pushPullRunner)


# Waiting for all threads to complete
for t in threads:
    t.join()
debug('Multithreading part complete')

# Check if all images were pushed successfully
info('Successfuly pushed ' + str(imagesPushed) + ' images of ' + str(len(imagesToSync)))
if imagesPushed < len(imagesToSync):
  print('Could not push all images. Please review the messages below and fix the error.')
  print('Images pushed successfully:')
  for imageName in imageNamesPushed:
    print('  ' + imageName)
  print('Images not pushed:')
  for image in imagesToSync:
    imageName = image['repositoryName'] + ':' + image['imageTags'][0]
    if imageName not in imageNamesPushed:
      print('  ' + imageName)  
  exit(errAWS)
else:
  print('All images were synchronized')
print('')

  
