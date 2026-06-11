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
- Column sorting by clicking the header
- Dashboard of current assignments includng yours, other team members and unassigned to your groups.
- Classification using 'type' and 'category'
- Case State classification
- Admin page to update/change users, add/remove groups, and update lists for: classification, state, type
- Supports attachments. they are stored as files, not in the databaes to reduce bloat
- Users can view and add comments/attachments to their submitted cases
- Can also change who submission is for, if not the actual submitter.
- Submissions automatically go to the 'triage' team.
- SLA and E-Mail notices, and search are planned but not there yet.

To get started, i would suggest a virtual environment. 
- Requirements.txt is there
- 2 example environment files are there for a few of the settings. You want your real one to be .env after review and possible edit. 
- Default admin password is in the .env file. Be sure to change that either in env or after first login to something a bit more complex.

to run: inside the project " flask run " (  could instead use gunicorn for larger organizations  )

Some screenshots below

<img width="1108" height="812" alt="image" src="https://github.com/user-attachments/assets/5078aaa1-e1c0-458f-8d29-3cd6e5ae2f52" />
<img width="1069" height="573" alt="image" src="https://github.com/user-attachments/assets/2cfe7a68-d7d9-460c-8b5d-2f8636e2fe48" />
<img width="1015" height="890" alt="image" src="https://github.com/user-attachments/assets/3b775516-bd36-44f1-92ca-c82f0af3425e" />
<img width="1034" height="560" alt="image" src="https://github.com/user-attachments/assets/5fa80519-800f-417e-bceb-a3d16b946bb7" />
<img width="1058" height="426" alt="image" src="https://github.com/user-attachments/assets/cd0362c3-9a94-45c7-a83c-5f457056717e" />
<img width="1069" height="452" alt="image" src="https://github.com/user-attachments/assets/6193bada-341c-4b78-b6db-96c0912f5011" />
<img width="1066" height="502" alt="image" src="https://github.com/user-attachments/assets/8a7827ef-4c38-4744-991c-12e28b546dc4" />





