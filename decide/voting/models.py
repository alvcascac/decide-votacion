from django.db import models
from django.contrib.postgres.fields import JSONField
from django.db.models.signals import post_save
from django.dispatch import receiver

from base import mods
from base.models import Auth, Key

from django.core.validators import URLValidator

from django.contrib.auth.models import User

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from authentication.models import UserProfile
from datetime import date

def age_calculator(birthdate):  
         
   today=date.today()

   try: 
       birthday = birthdate.replace(year=today.year)  
   except ValueError:   
       birthday = birthdate.replace(year=today.year, day=birthdate.day - 1) 
    
   if birthday > today:          
       return today.year - birthdate.year - 1 
   else: 
       return today.year - birthdate.year 



class PoliticalParty(models.Model):

    name = models.CharField(('Name'),max_length=200)
    acronym = models.CharField(('Acronym'),max_length=10)
    description = models.TextField(('Description'),blank=True, null=True)
    headquarters = models.CharField(('Headquarters'),max_length=200,help_text='The direction of the headquarters')
    image = models.CharField(('Image'),max_length=500,blank=True, null=True,help_text='Must be a link', validators=[URLValidator()])
    president = models.CharField(max_length=151, blank=True, null=True,help_text='You must do a primary presidential voting if you want select a new president')

    def __str__(self):
       return self.name

   
    class Meta:
        unique_together = (('name', 'acronym'),)


class Question(models.Model):
    desc = models.TextField()

    def __str__(self):
        return self.desc
   


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, related_name='options', on_delete=models.CASCADE)
    number = models.PositiveIntegerField(blank=True, null=True)
    option = models.TextField(help_text='You must put a valid username')

    def save(self):
        if not self.number:
            self.number = self.question.options.count() + 2
        return super().save()

    def __str__(self):
        return '{} ({})'.format(self.option, self.number)


class Voting(models.Model):
    name = models.CharField(max_length=200)
    desc = models.TextField(("Description"),blank=True, null=True)
    question = models.ForeignKey(Question, related_name='voting', on_delete=models.CASCADE)

    PRESIDENTIALPRIMARIES = 'PP'
    SENATEPRIMARIES = 'SP'
    SENATE = 'S'
    PRESIDENTIAL = 'P'

    TIPES_OF_VOTINGS = [
        (PRESIDENTIALPRIMARIES, 'Presidential primaries'),
        (SENATEPRIMARIES, 'Senate primaries'),
        (SENATE, 'Senate'),
        (PRESIDENTIAL, 'Presidential'),
    ]

    tipe = models.TextField(("Type"),blank=False, null=False, choices=TIPES_OF_VOTINGS)
    political_party = models.ForeignKey(PoliticalParty, related_name='voting', on_delete=models.CASCADE,blank=True, null=True,)


    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)

    pub_key = models.OneToOneField(Key, related_name='voting', blank=True, null=True, on_delete=models.SET_NULL)
    auths = models.ManyToManyField(Auth, related_name='votings')

    tally = JSONField(blank=True, null=True)
    postproc = JSONField(blank=True, null=True)

    def clean(self):
 
        if(self.tipe=='PP' or self.tipe=='SP'):

            politicalPartyVoting= self.political_party

            if(politicalPartyVoting== None):
                raise ValidationError(_('This type of votings must have political party.'))    
        
            question_id=self.question
            allQuestionOptions = QuestionOption.objects.filter(question_id = question_id)
            for questionOption in allQuestionOptions:
                
                try:
                    user = User.objects.get(username = questionOption.option)
                except:
                    raise ValidationError(_('You must put usernames in the question´s options.'))

                try:
                    userProfile = UserProfile.objects.get(related_user_id = user.id)
                except:
                    raise ValidationError(_('All the users in the options of the question must have a user profile.'))

                if(userProfile.employment=='M'):
                    raise ValidationError(_('The users in the options can not be a militant. He must have another  higher employment.'))

                if(self.tipe=='PP' and userProfile.employment=='S'):
                    raise ValidationError(_('The users in the options can not be a senator.'))
    
                elif(self.tipe=='SP' and userProfile.employment=='P'):
                    raise ValidationError(_('The users in the options can not be a president.'))
    
                years= age_calculator(userProfile.birthdate)
                print(years)
                if(years<18):
                    raise ValidationError(_('All users of the options must be over 18 years of age.'))

                politicalPartyUser = PoliticalParty.objects.get(pk = userProfile.related_political_party_id)
                if politicalPartyUser != politicalPartyVoting :
                    raise ValidationError(_('You must select users of the same political party that the voting.'))  

        elif(self.tipe=='P'): 

            politicalPartyVoting= self.political_party

            if(politicalPartyVoting!= None):
                raise ValidationError(_('This type of voting must not have a realted political party.')) 

            question_id=self.question
            allQuestionOptions = QuestionOption.objects.filter(question_id = question_id)
            for questionOption in allQuestionOptions:
                
                try:
                    user = User.objects.get(username = questionOption.option)
                except:
                    raise ValidationError(_('You must put usernames in the question´s options.'))

                try:
                    userProfile = UserProfile.objects.get(related_user_id = user.id)
                except:
                    raise ValidationError(_('All the users in the options of the question must have a user profile.'))

                userProfile = UserProfile.objects.get(related_user_id = user.id)
                hisPoliticalParty = userProfile.related_political_party

                if(hisPoliticalParty==None):
                    raise ValidationError(_('All the user profiles of the users in the options must have a related political party.'))     
                elif(hisPoliticalParty.president!=questionOption.option):
                    raise ValidationError(_('All the users in the options must be president of his corresponding political party.'))

    def create_pubkey(self):
        if self.pub_key or not self.auths.count():
            return

        auth = self.auths.first()
        data = {
            "voting": self.id,
            "auths": [ {"name": a.name, "url": a.url} for a in self.auths.all() ],
        }
        key = mods.post('mixnet', baseurl=auth.url, json=data)
        pk = Key(p=key["p"], g=key["g"], y=key["y"])
        pk.save()
        self.pub_key = pk
        self.save()

    def get_votes(self, token=''):
        # gettings votes from store
        votes = mods.get('store', params={'voting_id': self.id}, HTTP_AUTHORIZATION='Token ' + token)
        # anon votes
        return [[i['a'], i['b']] for i in votes]

    def tally_votes(self, token=''):
        '''
        The tally is a shuffle and then a decrypt
        '''

        votes = self.get_votes(token)

        auth = self.auths.first()
        shuffle_url = "/shuffle/{}/".format(self.id)
        decrypt_url = "/decrypt/{}/".format(self.id)
        auths = [{"name": a.name, "url": a.url} for a in self.auths.all()]

        # first, we do the shuffle
        data = { "msgs": votes }
        response = mods.post('mixnet', entry_point=shuffle_url, baseurl=auth.url, json=data,
                response=True)
        if response.status_code != 200:
            # TODO: manage error
            pass

        # then, we can decrypt that
        data = {"msgs": response.json()}
        response = mods.post('mixnet', entry_point=decrypt_url, baseurl=auth.url, json=data,
                response=True)

        if response.status_code != 200:
            # TODO: manage error
            pass

        self.tally = response.json()
        self.save()

        return self.do_postproc()

    def do_postproc(self):
        tally = self.tally
        options = self.question.options.all()

        opts = []
        for opt in options:
            if isinstance(tally, list):
                votes = tally.count(opt.number)
            else:
                votes = 0
            opts.append({
                'option': opt.option,
                'number': opt.number,
                'votes': votes
            })

        winner= opts[0]
        tie=False        
        for w in opts:
            if(w['votes'] > winner['votes']):
                winner=w

        optsWithoutWinner = opts
        optsWithoutWinner.remove(winner)
        for w in optsWithoutWinner:
            if(w['votes'] == winner['votes']):
                tie=True
                print('empate')
                break        
                
        if(self.tipe=='PP'):
            
            politicalParty = self.political_party
            user = User.objects.get(username = winner['option'])
            
            if(not(politicalParty.president == None)):
                oldPresidentUserProfile = UserProfile.objects.get(related_political_party = politicalParty, employment='P')
                oldPresidentUserProfile.employment = 'B'
                oldPresidentUserProfile.save()
           

            
            newPresidentUserProfile = UserProfile.objects.get(related_user_id = user.id)
            newPresidentUserProfile.employment = 'P'
            newPresidentUserProfile.save()
            
            politicalParty.president = winner['option']
            politicalParty.save()

        elif(self.tipe=='SP'):

            user = User.objects.get(username = winner['option'])
            newSenatorUserProfile = UserProfile.objects.get(related_user_id = user.id)
            newSenatorUserProfile.employment = 'S'
            newSenatorUserProfile.save()

        data = { 'type': 'IDENTITY', 'options': opts }
        postp = mods.post('postproc', json=data)

        self.postproc = postp
        self.save()
        return tie

    def __str__(self):
        return self.name




     
           
