# InstantCaseManagement
Simple case management tool     


Purpose is to be a simple web based case management tool for small groups. 
Current feature set
- Python + Flask based gunicorn is also an option for larger installs.
- User Signups
- SQLite back-end + SQL Alchemy if you need to change the database back-end for a larger concurrent user base.
- Group memberships
- Case assignments and routing
- Exporting to CSV
- Rudimentary search 
- Column sorting by clicking the header
- Columns can now be resized
- Dashboard of current assignments includng yours, other team members and unassigned to your groups.
- Classification using 'type' and 'category'
- Case State classification
- Admin pages to update/change users, add/remove groups, and update lists for: classification, state, type
- Supports attachments. they are stored as files, not in the databaes to reduce bloat
- Users can view and add comments/attachments to their submitted cases
- Can also change who submission is for, if not the actual submitter.
- Submissions automatically go to the 'triage' team.
- Can now manually create users and not rely on self-registration
- Email is now available
    - Can email user from case
    - Notices goes to assignee on assignment
    - Notice goes owner on comments added, SLA events
    - If no owner, notices of comments and events go to group manager
    - User gets email summary on resolution
    - Incoming mail for updates - **future feature**
- Groups now have a manager for notices
- Groups now have working hours, to use with OLA. ( not an industry standard, but was a request )
- Org level working hours for SLA.
- OLA
    - This is the 'pickup out of group' timer.
    - Each group can have their own pickup requirement, or none.
- SLA 
    - This is the resolution timer
    - Allocated time is based on case type. Can also be none.
    - Will pause clock when state is with customer, or waiting for approval to resolve. 
    - Clock will recalculate based on create time if case type is changed. it does not 'reset'.
- Now has a simple chat interface, accessable via main menu at the top.
    - Chat connects to extenral llama.cpp endpoints. One is for users, the other is for staff, so you can have targeted models if you like.
    - in env file it has the endpoint url and system prompt for each. You will want to adjust that to fit your needs.
 



To get started, i would suggest a virtual environment. 
- Requirements.txt is there
- 2 example environment file is there for a few of the settings. You want your real one to be .env after review and possible edit. 
- Default admin password is in the .env file. Be sure to change that either in env or after first login to something a bit more complex.

Some screenshots below

<img width="985" height="730" alt="image" src="https://github.com/user-attachments/assets/ab00f4f4-e773-4b16-a3fc-194374a0315c" />
<img width="881" height="609" alt="image" src="https://github.com/user-attachments/assets/36a5c53c-9836-40ef-8b04-9285c0f8ada0" />
<img width="559" height="331" alt="image" src="https://github.com/user-attachments/assets/0177bfcb-27e7-49b4-b710-e2491c4e2761" />
<img width="710" height="670" alt="image" src="https://github.com/user-attachments/assets/c250cdde-c080-4fde-a2d2-bc6b73f74ca7" />
<img width="747" height="434" alt="image" src="https://github.com/user-attachments/assets/b72d911f-9b85-4db8-bc39-803c72d4e1b1" />
<img width="942" height="663" alt="image" src="https://github.com/user-attachments/assets/6176875a-3852-4260-9697-e5076febdc24" />
<img width="894" height="792" alt="image" src="https://github.com/user-attachments/assets/95ca7ad5-8ebc-4aef-a55f-34dcf00c983f" />
<img width="479" height="90" alt="image" src="https://github.com/user-attachments/assets/b0a9b6bc-1f2f-4bb0-be4c-0635370ab231" />
<img width="1191" height="805" alt="image" src="https://github.com/user-attachments/assets/f8962608-45b8-4e7c-9abd-97d147f9f441" />
















