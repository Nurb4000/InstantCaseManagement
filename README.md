# InstantCaseManagement
Simple case management tool     **Warning --- Total code revamp in process. OpenCode is helping out with this**


Purpose is to be a simple web based case management tool for small groups. 
Current feature set
- Python + Flask based
- User Signups
- SQLite back-end + SQL Alchemy 
- Group memberships
- Case assignments and routing
- Exporting to CSV
- Rudimentary search 
- Column sorting by clicking the header
- Dashboard of current assignments includng yours, other team members and unassigned to your groups.
- Classification using 'type' and 'category'
- Case State classification
- Admin pages to update/change users, add/remove groups, and update lists for: classification, state, type
- Supports attachments. they are stored as files, not in the databaes to reduce bloat
- Users can view and add comments/attachments to their submitted cases
- Can also change who submission is for, if not the actual submitter.
- Submissions automatically go to the 'triage' team.- 
- SLA and E-Mail notices are planned but not there yet.

To get started, i would suggest a virtual environment. 
- Requirements.txt is there
- 2 example environment files are there for a few of the settings. You want your real one to be .env after review and possible edit. 
- Default admin password is in the .env file. Be sure to change that either in env or after first login to something a bit more complex.

to run: inside the project " flask run " (  could instead use gunicorn for larger organizations  )

Some screenshots below

<img width="1091" height="754" alt="image" src="https://github.com/user-attachments/assets/33fd535e-5f10-4d68-bc87-db25139895dd" />
<img width="1069" height="573" alt="image" src="https://github.com/user-attachments/assets/2cfe7a68-d7d9-460c-8b5d-2f8636e2fe48" />
<img width="1015" height="890" alt="image" src="https://github.com/user-attachments/assets/3b775516-bd36-44f1-92ca-c82f0af3425e" />
<img width="1034" height="560" alt="image" src="https://github.com/user-attachments/assets/5fa80519-800f-417e-bceb-a3d16b946bb7" />
<img width="1058" height="426" alt="image" src="https://github.com/user-attachments/assets/cd0362c3-9a94-45c7-a83c-5f457056717e" />
<img width="1034" height="466" alt="image" src="https://github.com/user-attachments/assets/0114ec2e-b3aa-4f6b-bdcb-5e016c615d8f" />
<img width="1157" height="475" alt="image" src="https://github.com/user-attachments/assets/952f5a6c-d678-4955-8cfa-baa2736dc9fb" />
<img width="1012" height="302" alt="image" src="https://github.com/user-attachments/assets/e0c99362-a0a8-4061-b199-3150105f427a" />
<img width="1086" height="369" alt="image" src="https://github.com/user-attachments/assets/d28001e6-7db9-47bb-992f-a05380851549" />







