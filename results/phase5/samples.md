# Phase 5 corpus-replay samples (qualitative reading only)

Replay of train+validation threads: annotated v1 entities, Phase 3 neural relations, Phase 4 candidates, Phase 5 reconciler. A simulated reviewer accepted creations only. There is no ground truth; these rows are for reading, not scoring.

## Update-type proposals (9)

- **UPDATE_STATUS** `blair-l_inbox_187` turn 2: “Lynn/Rick, Frank sent this to me last week and I have been working on it but I have one item for $1,406.01 that was listed on a report that Frank had that I can”  
  flags=[] match=[('T-1', 46.67)] note="cue='working on it'" tasks_in_thread=['these receivables get written off in order to clean up the books']
- **PROPOSE_DUE_DATE_CHANGE** `giron-d_inbox265` turn 1: “But I would prefer an afternoon or a late morning (10:30 a.m. or after) meeting.”  
  flags=['DATE_UNPARSEABLE', 'TENTATIVE_REQUEST', 'UNRESOLVED_NEW_DATE'] match=[('T-1', 82.5), ('T-2', 42.5), ('T-3', 42.5)] note="proposal needs confirmation; cue='prefer'" tasks_in_thread=['suggest the following dates to meet', 'let me know (and reply all in your response) if one or both dates work', 'will put together an agenda of the items for discussion']
- **COMPLETE_TASK** `jones-t_inbox894` turn 1: “I have now reviewed the documents and discussed them with my client.”  
  flags=['AMBIGUOUS_REFERENT'] match=[('T-1', 62.5), ('T-2', 62.5)] note='referent must be chosen by the reviewer' tasks_in_thread=['agreements reflect that TFS, Inc. be the Broker and thus, need to be signed', 'they should be returned to my attention for countersignature by Enron']
- **COMPLETE_TASK** `lay-k_inbox_474` turn 1: “I sent a note inviting Mr. Stelzer on Friday afternoon.”  
  flags=['THIRD_PARTY_COMPLETION'] match=[('T-1', 42.5)] note="cue='I sent'" tasks_in_thread=['sort things out']
- **PROPOSE_DUE_DATE_CHANGE** `mccarty-d_inbox6` turn 1: “Julie requested setting up this move after Linda Wehring's return next Monday, so request middle of next week churn date.”  
  flags=['AMBIGUOUS_REFERENT', 'UNRESOLVED_NEW_DATE'] match=[('T-1', 65.0), ('T-2', 62.5), ('T-3', 62.5)] note='referent must be chosen by the reviewer' tasks_in_thread=['requested to move from the 39th floor to EB1354', 'approved the move', 'schedule Dave for a move']
- **PROPOSE_DUE_DATE_CHANGE** `mccarty-d_inbox6` turn 1: “This will prevent moving the furniture from level 39, then having to replace it when I back-fill the office next week.”  
  flags=['AMBIGUOUS_REFERENT', 'UNRESOLVED_NEW_DATE'] match=[('T-1', 62.5), ('T-2', 62.5), ('T-3', 62.5)] note='referent must be chosen by the reviewer' tasks_in_thread=['requested to move from the 39th floor to EB1354', 'approved the move', 'schedule Dave for a move']
- **COMPLETE_TASK** `watson-k_inbox459` turn 1: “I reviewed your spreadsheets and had 2 changes, they are in red text with a green shade.”  
  flags=['THIRD_PARTY_COMPLETION'] match=[('T-1', 42.5)] note="cue='I reviewed'" tasks_in_thread=["Let me know if we're syncing-up"]
- **CANCEL_TASK** `wolfe-j_inbox1` turn 1: “And Lissa's wedding has been cancelled, but I will still be haning out with Shelly on Saturday night.”  
  flags=['AMBIGUOUS_REFERENT'] match=[('T-1', 42.5), ('T-2', 42.5)] note='referent must be chosen by the reviewer' tasks_in_thread=["'ll be ready", 'trying to get some poker together']
- **PROPOSE_DUE_DATE_CHANGE** `wolfe-j_inbox1` turn 1: “I think I am staying with Becky at the beginning of the week at least, though Lissa has moved in with her now, so that might get a little crowded.”  
  flags=['AMBIGUOUS_REFERENT', 'UNRESOLVED_NEW_DATE'] match=[('T-1', 62.5), ('T-2', 62.5)] note='referent must be chosen by the reviewer' tasks_in_thread=["'ll be ready", 'trying to get some poker together']

## Flagged NO_ACTION (20)

- **NO_ACTION** `beck-s_inbox5` turn 0: “Ready for settlements draft (draft issue is resolved).”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `buy-r_inbox90` turn 0: “Ray, We are working on revising the DASH template in order that it can be readily used for asset divestitures, contract terminations, and amendments to transact”  
  flags=['NO_REFERENT'] match=[] note='UPDATE_STATUS without a matching task' tasks_in_thread=[]
- **NO_ACTION** `campbell-l_inbox231` turn 0: “The agenda is to hear presentations about, and discuss, ICAP theological issues (originally scheduled for the Sept. 11 meeting that was cancelled.)”  
  flags=['NO_REFERENT'] match=[] note='CANCEL_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `crandell-s_inbox122` turn 1: “I am working on getting access to the World Trade Center distribution list.”  
  flags=['NO_REFERENT'] match=[] note='UPDATE_STATUS without a matching task' tasks_in_thread=[]
- **NO_ACTION** `derrick-j_inbox100` turn 0: “Kind regards Andrew House < < 010606_Petition .doc > > _____________________________________________________________ This e-mail is sent by or on behalf of Link”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `donoho-l_inbox35` turn 1: “Just to let everyone know, I had called Audrey on Tuesday, Oct. 23rd at 4:30 p.m. to inform her that we need to reschedule this meeting and move it to the next ”  
  flags=['NO_REFERENT'] match=[] note='DATE_CHANGE without a matching task' tasks_in_thread=[]
- **NO_ACTION** `donoho-l_inbox35` turn 1: “I have spoken to everyone in Mike's group and everyone will be available on the following dates: Oct. 29 Monday, Oct. 30 Tuesday, and Nov. 2 Friday Audrey, plea”  
  flags=['NO_REFERENT'] match=[] note='DATE_CHANGE without a matching task' tasks_in_thread=[]
- **NO_ACTION** `haedicke-m_inbox_58` turn 0: “The lawsuit was filed at 11:06 a.m. The next thing to do is to get MSN formally served.”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `jones-t_inbox974` turn 0: “Hi Tana, A couple of weeks ago I sent up to you (I think it was you) the letter I received regarding an assignment between Transcanada and Mirant.”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `keiser-k_inbox13` turn 0: “As of now, the move for the 6 th floor is scheduled for Friday (2/8).”  
  flags=['NO_REFERENT'] match=[] note='DATE_CHANGE without a matching task' tasks_in_thread=[]
- **NO_ACTION** `lokey-t_inbox158` turn 1: “We will reschedule for Monday, 10/8 as soon as we get a time for the video conference rooms.”  
  flags=['NO_REFERENT'] match=[] note='DATE_CHANGE without a matching task' tasks_in_thread=[]
- **NO_ACTION** `martin-t_inbox_277` turn 0: “Please also let me know if Tom is the person who needs to call and inquire about it, as you suggested may be the case since it is handled outside of Enron.”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `mims-thurston-p_inbox18` turn 0: “This group obviously does not include everyone, but we have most of our major relationships (and it is the official list that has been submitted to UBS for cred”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `nemec-g_inbox1129` turn 0: “Brian & Jean, In trying to move the BH 2001 Comp Plan along, Jack and I have signed the attached docs and you will be receiving the original for your signature ”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `nemec-g_inbox1129` turn 0: “Brian and Jeanie, I have changed the resolutions slightly from what I sent over to you on 7/12.”  
  flags=['NO_REFERENT'] match=[] note='COMPLETE_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `reitmeyer-j_inbox93` turn 1: “I'm working on the problem, but haven't a solution yet.”  
  flags=['NO_REFERENT'] match=[] note='UPDATE_STATUS without a matching task' tasks_in_thread=[]
- **NO_ACTION** `salisbury-h_inbox268` turn 0: “Again, he is trying to fill up a class that is about to be cancelled, and I think he would be willing to negotiate.”  
  flags=['NO_REFERENT'] match=[] note='CANCEL_TASK without a matching task' tasks_in_thread=[]
- **NO_ACTION** `shackleton-s_inbox298` turn 0: “We could move the Convertible Arbitrage Book back into ECT Investments before year-end.”  
  flags=['NO_REFERENT'] match=[] note='DATE_CHANGE without a matching task' tasks_in_thread=[]
- **NO_ACTION** `shackleton-s_inbox341` turn 0: “Can we do this lettter instead of going the Corporate Secretary route to get it done?”  
  flags=['NO_REFERENT'] match=[] note='UPDATE_ASSIGNEE without a matching task' tasks_in_thread=[]
- **NO_ACTION** `skilling-j_inbox_1249` turn 0: “The BMC Tour of Houston has been cancelled.”  
  flags=['NO_REFERENT'] match=[] note='CANCEL_TASK without a matching task' tasks_in_thread=[]

## Duplicate / restatement handling (10)

- **CREATE_TASK** `buy-r_inbox396` turn 1: “Ellen and I just spoke and she is putting together some information regarding the range of values, size of the transaction, etc. that I would suggest we include”  
  flags=['POSSIBLE_DUPLICATE', 'UNKNOWN_PERSON'] match=[('T-1', 42.5), ('T-3', 42.5)] note='evidence=resolved_assignee' tasks_in_thread=['spoke', 'the potential sale of E & P portfolio should be described and approved', 'spoke', 'thoughts are']
- **NO_ACTION** `derrick-j_inbox150` turn 3: “Perhaps Haedicke's group, which is obviously much bigger than ours, could continue to do this at least until we add another person and then reassess the situati”  
  flags=['RESTATED_EXISTING_TASK'] match=[('T-1', 42.5)] note='restates T-1' tasks_in_thread=["continue to request support from Mark Haedicke's group", 'is there someone', "'d like to discuss"]
- **CREATE_TASK** `keiser-k_inbox245` turn 2: “If possible, please forward these MTM values to me by the end of the day.”  
  flags=['AMBIGUOUS_ASSIGNEE', 'DATE_PARTIAL', 'POSSIBLE_DUPLICATE'] match=[('T-1', 25.83)] note='evidence=request_cue' tasks_in_thread=['calculate our MTM values on those dates', 'forward them to me']
- **CREATE_TASK** `nemec-g_inbox1679` turn 1: “Can you please review the attached Letter of Interest and provide any comments.”  
  flags=['MULTIPLE_ASSIGNEES', 'POSSIBLE_DUPLICATE', 'WEAK_RELATION_SCORE'] match=[('T-3', 20.0), ('T-4', 20.0)] note='evidence=request_cue' tasks_in_thread=['Review', 'make any minor changes', 'get these out to Shell Capital (Risks & Mitigants, Schedule) and Nicor (Letter of Interest, Letter of Intent, and Schedule)', 'would have Gerald take a look at the Letter of Interest']
- **CREATE_TASK** `smith-m_inbox274` turn 1: “I could leave work pretty much anytime on wednesday, so just let me know.”  
  flags=['POSSIBLE_DUPLICATE', 'UNKNOWN_PERSON'] match=[('T-3', 42.5), ('T-6', 42.5)] note='evidence=request_cue' tasks_in_thread=['have a trip', "'ll be passing through IAH", 'let me know what your plans', 'Matt & I see each other']
- **CREATE_TASK** `watson-k_inbox218` turn 2: “I will let you know as others are identified.”  
  flags=['POSSIBLE_DUPLICATE'] match=[('T-3', 9.17)] note='evidence=request_cue' tasks_in_thread=['have requested that we be kept current on the status', 'will contact Jennifer Kennedy, Jerry Moore, Gavin Russo and Warren Schick with this email to make sure that there are no state income, franchise tax, sales and use or ad valorem tax issues', 'let me know your thoughts']
- **CREATE_TASK** `heard-m_inbox_master_netting3` turn 1: “Marie: I received your e-mail re the revisions to the Master Netting Agreement.”  
  flags=['POSSIBLE_DUPLICATE'] match=[('T-1', 21.25)] note='evidence=resolved_assignee' tasks_in_thread=['will be working on the Master Netting Agreement', 'I need the following from the credit group: 1. a list', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation and chief executive office for each of the Reliant entities 3. credit terms']
- **CREATE_TASK** `heard-m_inbox_master_netting3` turn 1: “I will not be in the office later this afternoon and want to make sure that Dede Russo at Reliant receives a first draft today.”  
  flags=['DATE_UNPARSEABLE', 'POSSIBLE_DUPLICATE'] match=[('T-4', 42.5), ('T-5', 42.5)] note='evidence=request_cue' tasks_in_thread=['will be working on the Master Netting Agreement', 'I need the following from the credit group: 1. a list', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation and chief executive office for each of the Reliant entities 3. credit terms']
- **CREATE_TASK** `heard-m_inbox_master_netting3` turn 1: “Jay Williams in credit is going to work with me on the Reliant Master Netting Agreement.”  
  flags=['POSSIBLE_DUPLICATE', 'WEAK_RELATION_SCORE'] match=[('T-1', 35.83)] note='evidence=request_cue' tasks_in_thread=['will be working on the Master Netting Agreement', 'I need the following from the credit group: 1. a list', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation and chief executive office for each of the Reliant entities 3. credit terms']
- **CREATE_TASK** `heard-m_inbox_master_netting3` turn 1: “I will not be in the office on Wednesday, so I would love to have copies of all the Reliant documents for Thursday morning.”  
  flags=['DATE_UNRESOLVED_NO_ANCHOR', 'POSSIBLE_DUPLICATE'] match=[('T-4', 42.5), ('T-5', 42.5)] note='evidence=request_cue' tasks_in_thread=['will be working on the Master Netting Agreement', 'I need the following from the credit group: 1. a list', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation', 'I need the following from the credit group: 1. a list of the Reliant entities with whom Enron trades as well as a list of all relevant contracts 2. state of incorporation and chief executive office for each of the Reliant entities 3. credit terms']

## Sample creations (15)

- **CREATE_TASK** `buy-r_inbox1141` turn 0: “Michael, I want you to have one initial comment.”  
  flags=[] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `buy-r_inbox899` turn 0: “Hayslett; Terri Peschka; vladimir.gorny @ enron.com Please see the attached draft limits document which was discussed at PGE's Sept. 6th Risk Management Committ”  
  flags=[] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `campbell-l_inbox1027` turn 0: “ATTENTION: To participate in the PJM Day Ahead Market Trials, please login and submit bid and offer information to the following Market Trials web site < https:”  
  flags=[] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `cash-m_inbox116` turn 1: “Thus, we need to be careful about the terminology used for the WARN notice period.”  
  flags=['NO_ASSIGNEE'] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `cash-m_inbox28` turn 1: “I'll forward additional information as I receive it. cs”  
  flags=['DATE_EVENT_CONDITION', 'WEAK_RELATION_SCORE'] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `corman-s_inbox25` turn 0: “A couple of further things that I need: - I need to reconcile the net volume on Galen's sheet by month with the net cash out volumes on Jim's sheet.”  
  flags=[] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `derrick-j_inbox151` turn 0: “Given that change, would you like for me to continue to request support from Mark Haedicke's group or is there someone in the corporate area you'd rather I appr”  
  flags=['AMBIGUOUS_ASSIGNEE'] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `derrick-j_inbox151` turn 1: “Heath, I'm on the road and communicating via Blackberry.”  
  flags=[] match=[] note='evidence=resolved_assignee' tasks_in_thread=["continue to request support from Mark Haedicke's group", 'is there someone', "'d like to discuss"]
- **CREATE_TASK** `donoho-l_inbox_junk_file418` turn 2: “Also, currently in production today Socal Needles point 10487 is set up as a passive point for confirmation.”  
  flags=[] match=[] note='evidence=resolved_assignee' tasks_in_thread=['discussing', 'run it past SoCal']
- **CREATE_TASK** `germany-c_inbox398` turn 0: “Please let me know as soon as possible.”  
  flags=[] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `giron-d_inbox265` turn 0: “I would like to suggest the following dates to meet in Houston.”  
  flags=['COMPETING_DATES', 'DATE_PARTIAL'] match=[] note='evidence=resolved_assignee' tasks_in_thread=[]
- **CREATE_TASK** `hayslett-r_inbox24` turn 0: “As such, please talk with your CAO's and/or BU leaders as part of your 2002 risk assessment and obtain answers to the following questions and send them back to ”  
  flags=['AMBIGUOUS_ASSIGNEE'] match=[] note='evidence=request_cue' tasks_in_thread=[]
- **CREATE_TASK** `heard-m_inbox_289` turn 1: “If y'all could just check the times of the movies and let me know when to be there, I will appear with bells on.”  
  flags=['NO_ASSIGNEE'] match=[] note='evidence=request_cue' tasks_in_thread=['would you like']
- **CREATE_TASK** `hernandez-j_inbox72` turn 1: “Check it out and pass it around for him.”  
  flags=['WEAK_RELATION_SCORE'] match=[] note='evidence=resolved_assignee' tasks_in_thread=[]
- **CREATE_TASK** `hernandez-j_inbox72` turn 2: “Here's a guy I played football with that you guys should at least bring in for an interview.”  
  flags=['NO_ASSIGNEE'] match=[] note='evidence=request_cue' tasks_in_thread=['Check it out', 'pass it around for him', 'home number']
