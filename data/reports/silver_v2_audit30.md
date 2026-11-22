# SILVER v2 deterministic 30-record quality audit

Seed: `20261102`. The sample excludes all 30 records used to create the v2 rules.
This is AI-assisted manual inspection, not independent human verification and not GOLD.

## Summary

- Records: 30
- Ratings: {'acceptable': 8, 'major': 10, 'minor': 12}
- v2 entities in sample: {'PERSON': 33, 'TASK': 39, 'TEMPORAL': 36}
- SILVER-v1 comparison: 22 major, 6 minor, 2 acceptable in the original diagnostic audit.

## Records

### mailex:train:blair-l_inbox_187:turn_0001

Rating: **acceptable** — Empty-task negative is correct; the social closing is no longer a TASK.

V2 spans: (none)

> FYI. Thanks. Lynn

### mailex:train:buy-r_inbox380:turn_0001

Rating: **major** — The explicit current assignment to act as point person is omitted.

V2 spans: (none)

> just a note to the team .... the restructuring concept has not yet been presented to Duferco, but will be shortly, and as of our meeting this morning, Gregg Hermans is tasked with being the single point person from Enron in dealing with Duferco on these issues.

### mailex:train:cash-m_inbox8:turn_0000

Rating: **major** — `has not returned my call` is historical state but remains labeled TASK.

V2 spans: PERSON='Mike'; TASK='forward to their attention'; TEMPORAL='tomorrow, Sunday and Monday'; TASK='has not returned my call'; TEMPORAL='until Monday'; TASK='will forward the name'; TEMPORAL='early Monday'; TEMPORAL='as of yet'

> Mike, I could not find Ms. Cash or Mr. Johnson on the email, please forward to their attention. Black & Veach Legal Counsel - Mr. Tony Kelly on staff in Kansas City, MO (913) 458-2000 OCI contacted sheriff's office and they will be on site tomorrow, Sunday and Monday. Additionally as required. FMM's Mike Feduccia has not returned my call, he is out of town until Monday. He has retained legal counsel and I will forward the name and address early Monday. No labor agreements have surfaced in the queries as of yet. Lark Mulvahill

### mailex:train:derrick-j_inbox_216:turn_0000

Rating: **minor** — Plans and meeting are captured, but `attached please find` is document presentation, not TASK.

V2 spans: TASK='attached please find the relevant biographical information'; TASK='plan to be in Houston to complete my tenure at American General'; TEMPORAL='from November 28-30'; TASK='would be pleased to meet'; TEMPORAL='that time or any other time that is convenient'

> As we discussed, attached please find the relevant biographical information for Thomas Ferrigno and me. As you know, I plan to be in Houston to complete my tenure at American General from November 28-30. I would be pleased to meet at that time or any other time that is convenient. Over the course of the next two weeks I can be most easily reached through my American General voice mail (713-831-8893) which I check frequently. Alternatively, messages can be left for me at Hughes Hubbard at 202-721-4770. < < BIO-TF.DOC > > < < KTA Business Development Bio.DOC > > (See attached file: BIO-TF.DOC) (See attached file: KTA Business Development Bio.DOC) - BIO-TF.DOC - KTA Business Development Bio.DOC

### mailex:train:donoho-l_inbox_junk_file369:turn_0002

Rating: **acceptable** — Descriptive numeric statement correctly remains an empty-task negative.

V2 spans: (none)

> I have 1.8 Bcf/d for annual daily average for total system in 2001 on TW.

### mailex:train:donoho-l_inbox_junk_file418:turn_0002

Rating: **minor** — Action spans are plausible, but explicit person Mary Draemer is omitted.

V2 spans: PERSON='Lindy'; TEMPORAL='during the timely cycle'; TASK='confirm this Socal Topock point via EDI'; TASK='give us a window like they do at Socal needles'; TASK='will need to complete the Operator Choice request form that is posted on the TW web site'

> Lindy, Since Socal will not be confirming during the timely cycle, this gas will be incremental and the supplies may not get scheduled. Also, I know Socal confirms the Needles point via EDI. Will they also confirm this Socal Topock point via EDI? If they do confirm via EDI, it would be good to have them work with Mary Draemer on a test EDI file. Will they give us a window like they do at Socal needles? Today in TMS, we do have a Non Grid cycle that runs just prior to the gas day starting at 7:30 am. I know Socal does not confirm this cycle today for Needles. Also, currently in production today Socal Needles point 10487 is set up as a passive point for confirmation. This Topock point would need to be set up with the same point status role for confirmation if they confirm this point via EDI. Socal will need to complete the Operator Choice request form that is posted on the TW web site. Thanks Ramona

### mailex:train:germany-c_inbox193:turn_0000

Rating: **minor** — Requests and plan are captured; the explicit 5/31/2002 date is omitted.

V2 spans: PERSON='Robert'; TASK='please give me all the service deal numbers'; PERSON='Marlene'; TASK='going to send CGLF a termination notice'; TASK='Let me know'

> Robert, when you get a chance, please give me all the service deal numbers for CGLF k #37393. Marlene, the new termination date for this contract is 5/31/2002. If I have time, I am going to send CGLF a termination notice for this contract effective 5/31/2002. Is that something you could do for me? Let me know.

### mailex:train:lavorato-j_inbox260:turn_0002

Rating: **minor** — No TASK is correct, but `a couple days after I left` is a temporal expression.

V2 spans: (none)

> 800 and something a couple days after I left.

### mailex:train:lokey-t_inbox_814:turn_0000

Rating: **minor** — Main requests and planned draft are correct; signature-name coverage is incomplete.

V2 spans: TASK='review the attached interconnect agreement between Transwestern and Questar'; TASK='reply back to me with any comments'; TASK='would like to send a draft to Questar'; TEMPORAL='Tuesday morning, January 22, when we return from our holiday'; PERSON='Bill'; PERSON='Robert'; TASK='see the red-lined language addressing the tax reimbursement'

> All, Please review the attached interconnect agreement between Transwestern and Questar. It is fully reimbursable by Questar. This interconnect will be a delivery point to Questar in the Blanco Hub. FYI, the section of pipe that we are connecting the interconnect to is owned by Transwestern and is not part of the jointly owned facilities of the Blanco Hub. If you have any questions, please feel free to call me to discuss. Please reply back to me with any comments you may have. I would like to send a draft to Questar on Tuesday morning, January 22, when we return from our holiday. Bill and Robert - please see the red-lined language addressing the tax reimbursement. Thanks for your time, Kim. X33098 < < File: Questar So Trails Hub Interconnect 01-15-02.doc > >

### mailex:train:martin-t_inbox414:turn_0001

Rating: **minor** — Forwarding request and times are correct; explicit signature/name coverage is incomplete.

V2 spans: TEMPORAL='tomorrow'; TEMPORAL='9:30'; TASK='Please pass this along to the people in your group that you want to attend'

> Pira will be in the office for a power briefing tomorrow at 9:30 in ECS 5990. The power group said they have a few open seats for the gas group (2-3 per desk). Please pass this along to the people in your group that you want to attend. Thanks, Chris

### mailex:train:martin-t_inbox487:turn_0000

Rating: **major** — The email asks for feedback and customer names, but no TASK is retained.

V2 spans: PERSON='Tom'; PERSON='Michael Salinas'; TEMPORAL='THIS MONDAY, December 3rd'; TEMPORAL='5:00'

> Tom, Michael Salinas is planning the Christmas Card Signing Party. It looks like it's going to be at Cabo's THIS MONDAY, December 3rd at 5:00. I assume that we will be splitting the cost, but I guess I really shouldn't assume because of everything the company is going through right now. Michael estimates the total cost to be $1000, making your half $500. Let me know what you think. Also, are there any customers (for the trading side) that we need to be sure are included to receive Christmas cards? Thanks, Laura

### mailex:train:martin-t_inbox_349:turn_0001

Rating: **minor** — Core discussion and forwarding commitments are present; one PERSON boundary is shortened and a follow-up commitment is omitted.

V2 spans: PERSON='Gary Bryan'; PERSON='Tom'; PERSON='Jim'; TASK="Let's discuss"; TEMPORAL='1:30'; TASK="'ll forward any changes to Jeff Hodge in preparation of the Alliance Draft"; PERSON='Jeff'; TEMPORAL='following our meeting'

> Gary Bryan, Tom, and Jim: Let's discuss at 1:30 and then I'll forward any changes to Jeff Hodge in preparation of the Alliance Draft. Jeff, I'm sending this just for fyi until after me and the guys meet. I'll get with you following our meeting.

### mailex:train:mccarty-d_inbox_alaska_gas111:turn_0001

Rating: **minor** — Several future commitments are recovered, but planned agreement/finish actions are incomplete.

V2 spans: PERSON='Joe H.'; TEMPORAL='Friday'; TASK='going to start meeting'; PERSON='Joe Hartsoe'; PERSON='Danny'; TEMPORAL='Last week'; TEMPORAL='2 days'; TASK='will attend the Los Angeles meeting'; TEMPORAL='12th'; TEMPORAL='before Christmas'; TEMPORAL='early January'; TASK='will forward the executive summary'

> Joe H. and I were both on the Friday conf. call arranged by Dennis regarding the press release in response to the introduction of the Producer's enabling legislation in the Senate. Nothing worth reporting. None of the companies (except perhaps TCPL) thought that a press release should be issued so the release idea was dropped. The companies ' DC reps are going to start meeting re Alaskan matters and I believe Joe Hartsoe will cover those meetings for Enron. Danny here is my weekly report. Last week I attended the Calgary meetings (2 days). I will attend the Los Angeles meeting of the commercial group on the 12th. We hope to agree on the model assumptions and finish the proposal before Christmas. An early January meeting is planned with the Producers to go through the commercial proposal which will now have several binders of detail attached to the proposal. I will forward the executive summary of the draft proposal. Bob Hill.

### mailex:train:mclaughlin-e_inbox404:turn_0000

Rating: **minor** — Future sending is correct; `have a call in` reports an action already initiated and should not be a new TASK.

V2 spans: TASK='have a call'; PERSON='Carol St.Clair'; TASK="'ll send it up"

> I got the fax and have a call in to Carol St.Clair to confirm placement and particular language for the insertion. I'll send it up as soon as I can.

### mailex:train:nemec-g_inbox113:turn_0002

Rating: **acceptable** — Short document-delivery acknowledgement contains no actionable task.

V2 spans: (none)

> Oops - here they are ...

### mailex:train:reitmeyer-j_inbox135:turn_0000

Rating: **acceptable** — Notification commitments and the call instruction are represented conservatively.

V2 spans: TASK='will notify you when we have filed each segment with FERC for approval'; TEMPORAL='Upon receiving FERC approval'; TASK='will notify you of the contract in service date for that segment of capacity'; TEMPORAL='September 25'; TASK='Please call'

> Dear Medicine Bow Shipper: Based on your concerns and requests for additional notice prior to commissioning each additional segment, we are adopting the following procedure for placing segments in service: We will notify you when we have filed each segment with FERC for approval. Based on our experience with the tie-ins to date, we are now anticipating 4 days for approval. Upon receiving FERC approval, we will notify you of the contract in service date for that segment of capacity. The contract will start at the later of the following dates: 1) two days following the date of FERC approval; 2) 4 days following filing with FERC; or 3) at least one week following the last in service date. For example, we officially filed for the second segment approval (61 Mdth/day) September 25 (today) and anticipate filing the next segment (79 Mdth/day) on October 1. If we receive FERC approval tomorrow, we will notify you, but the contract will not become effective until Sept 29. However, you would have additional capacity available a couple days early at $.1434. Hopefully, the above procedure will help you to plan for your nominations by providing more flexability and notice for each additional commissioning. Please call me to discuss or with any questions. Laine Lobban

### mailex:train:reitmeyer-j_inbox365:turn_0001

Rating: **minor** — Most tasks are correct, but slash-separated people are combined and one setup action is omitted.

V2 spans: PERSON='George/Russ'; TASK='bounce the servers'; TASK='notify Frank'; PERSON='Carole'; TASK='Please send Cecilia/Margie and me the name of the new pub_code (i.e GDP-PSCO/CITIGAT)'; TEMPORAL='After George/Russ contacts you regarding bouncing servers'; TASK='the rate handle will need to be attached to the deal no. in Sitara'; PERSON='Cecilia/Margie'; TASK='map the pubcode in ERMS'; TEMPORAL='after it is sent to you by Carole'; PERSON='Phil/Don'

> * Please note, I have set-up the rate server handle #27470 - PSCO.CITYGATE.GDP.D.A George/Russ: Please bounce the servers and notify Frank so he can have the deal attached. Carole: Risk needs to set-up this curve in ERMS. Please send Cecilia/Margie and me the name of the new pub_code (i.e GDP-PSCO/CITIGAT). After George/Russ contacts you regarding bouncing servers, the rate handle will need to be attached to the deal no. in Sitara. Cecilia/Margie: Please map the pubcode in ERMS after it is sent to you by Carole. PSCO is found under Citygates. Phil/Don: Please be sure this rate handle is included on the validation report. Thanks: Kelly @ 5.8491

### mailex:train:reitmeyer-j_inbox432:turn_0000

Rating: **major** — The reminder communicates an actionable fuel-bid deadline, but both TASK and `tomorrow` are absent.

V2 spans: (none)

> Just wanted to remind you that the fuel bid for December (!) is due tomorrow. The volume has been 500 - 1000 MMbtu. Thanks, Scott Sitter

### mailex:train:salisbury-h_inbox728:turn_0000

Rating: **major** — A non-temporal clause is labeled TEMPORAL and the email's go-forward actions are not represented.

V2 spans: TEMPORAL='Last Friday'; TEMPORAL='when your site will be able to'

> All, The viewing of the All Employee Meeting today was not a complete success despite our successful testing yesterday. There were several IT teams (your local IT Support as well as Houston based Web and Network teams) that worked together to troubleshoot the audio and video feeds while watching the performance of your sites communication links with Houston to ensure your trading business was not compromised. I would like to provide you some history as well as go forward actions to provide better audio/video streaming services. You may have noticed that the medium for viewing the meeting has changed from the previous IPTV application to a web based application. This new medium has been in the development stages with the production target of October 2001 which was set by business. Last Friday business approached IT infrastructure and advised that there would be an All Employee Meeting on Aug, 16 (today). This didn't provide much time for preparation and testing. During the troubleshooting for each of your sites, the Network team (Scott Shishido and George Nguyen) were able to determine some but not all causes to the poor performance. I will be meeting with the Web (Edward Ray) and Network (Steve Hardy and Scott Shishido) teams to determine what the action plan is for resolving the performance issues. My understanding is that the meeting will be available for viewing if you wish to do so. I will be communicating to you when your site will be able to view this replay of the All Employee Meeting. Please contact me if you have any questions or concerns. Regards, Dan Dietrich

### mailex:train:schoolcraft-d_inbox68:turn_0000

Rating: **major** — The explicit instruction to send a representative is omitted.

V2 spans: TEMPORAL='over next few months'; TEMPORAL='begin at 1:00 p.m.'; TEMPORAL='March 21 April 4 April 18 May 2 May 9'

> Meetings will be held over next few months to discuss the offsite tests. Each meeting will begin at 1:00 p.m. in conference room EB39C1 and last approximately an hour. The meeting dates are as follows: March 21 April 4 April 18 May 2 May 9 If you are unable to attend please send a representative. Sharon Brown ETS Gas Control 713-853-5660

### mailex:train:schoolcraft-d_inbox_junk648:turn_0003

Rating: **minor** — Installation plan is represented, though the check span is fragmentary and one planned action is incomplete.

V2 spans: TASK='proceed with the unloader installation at any time'; PERSON='Ed'; PERSON='Jon'; TEMPORAL='through the 22nd'; TEMPORAL='the week of the 25th'; TASK="'ll check"; PERSON='Gene'; TEMPORAL='the week of the 25th'

> All Per Darrell and Jerry's comments below, we can proceed with the unloader installation at any time. I talked to Ed and had a message from Jon. Jon is tied up in Florida through the 22nd, probably. He can be at Station 8 the week of the 25th. He'll check and confirm that. Gene and I talked and we'll plan on doing the install on both units (one at a time) the week of the 25th. Thanks Mike

### mailex:train:shackleton-s_inbox298:turn_0001

Rating: **acceptable** — The request to think about the issue and named person are captured.

V2 spans: TASK='think about this'; PERSON='Farzad'

> Gary, Have you had a chance to think about this? Farzad says it does not matter to him whether he trades as ENA, ECT Investments or XXX. One important thing I just thought about is that I do not think we would want the Convertible Arbitrage Book Trading in London as Enron North America Corp. Whether we are trading from London or Houston, our counterparties will be the same on Convertible Arbitrage Trading though the% s may change. We use the Agent, Enron Investment Services Limited in London, to trade on behalf of ECT Investments, Inc. Thanks, Sheila

### mailex:train:skilling-j_inbox1385:turn_0001

Rating: **minor** — Historical narrative correctly has no TASK; the final temporal boundary is malformed.

V2 spans: TEMPORAL='Last night'; PERSON='John Miller'; PERSON='Randall Harman'; PERSON='John Grumbles'; PERSON='Mark Hillstrom'; PERSON='Rita Harman'; PERSON='Woody'; TEMPORAL='weekend of October 27th-be'

> Brother Beta's: Last night we had a GREAT Beta gathering here in Atlanta. The pictures were taken at John Miller's house. In attendance: Beta's John Miller, Randall Harman, John Grumbles, and Mark Hillstrom and myself. We also had Rita Harman and their two kids, Meredith and Kyle, Woody's 2 sons, Matt and Adam, as well as Mark Hillstrom's son, Ryan. Mark's son was in Atlanta to play in the U.S. Amateur golf championship. We feasted on Woody's great ribs and his Awesome Woody Blossom and drank a few too many beers (you can't see us singing in a couple of the pictures but we did!!) Foosball was one of the activities, as was a phone call to Phil and Annie Morrow in Rockford, Il. The picture of John Miller is NOT with his wife, April; it's with Randall Harman's daughter, Meredith. Some things never change (thank God and Wooglin), enjoy the pics, -kai- Chuck P.S. Homecoming is the weekend of October 27th-be there! Beta tailgating on campus-what could be better!! ________________________________________ Chuck Paul

### mailex:train:skilling-j_inbox_1530:turn_0002

Rating: **acceptable** — Informational status message has no explicit new request.

V2 spans: (none)

> Jeff, info on the latest draw. Everything seems Ok with the exception of some unsigned forms by you or your representative as well as the revised draw request.

### mailex:train:taylor-m_inbox78:turn_0000

Rating: **acceptable** — Planned call and explicit review/forward requests are represented with named people and date.

V2 spans: PERSON='Craig'; PERSON='Chris Balmer'; PERSON='Pam Jaynes'; TASK='will be giving you a call'; TEMPORAL='Tuesday'; TASK='Please review the attachment'; TASK='pass them along to whomever may need to be involved at your company'

> Craig, As we discussed on Thursday, LG & E is preparing to enter into a hedge plan. LG & E's hedge plan is based on the use of call options. The Public Service Commission is expected to act on that proposal in the next few days. Chris Balmer, Pam Jaynes, and I will be giving you a call on Tuesday to discuss LG & E's hedging plan, seek your comments, and address any issues or concerns you may have in advance of actually sending out the bid letters. We believe it will be useful to seek your input and answer any questions you may have at this point, since once regulatory approval is received the time to implement the program, seek bids, and consummate transactions will all have very short turn around times. Attached are two documents which will be the basis of that discussion. The first is a draft Bid Letter and the second is the General Terms and Conditions under which the call options will be purchased. Please review the attachment and pass them along to whomever may need to be involved at your company. Thanks Clay - bidlet draft 09-24-01.doc - GT & C.doc

### mailex:train:white-s_inbox132:turn_0001

Rating: **major** — The central `begin gathering` request is omitted while only a dependent temporal clause remains.

V2 spans: TEMPORAL='after I receive further clarification on some items from Shona'

> Tim - Can you go ahead and begin gathering the number of books and traders we had at 11-30?! All - Other instructions will follow after I receive further clarification on some items from Shona Thanks! Casey

### mailex:train:whitt-m_inbox288:turn_0000

Rating: **major** — The explicit instruction to double-click the attached files is omitted.

V2 spans: (none)

> Here's one I ran across. Not huge, but great location (walk to the gondola). VERY rentable. Randy To view these listings, double click on the attached files.

### mailex:train:wolfe-j_inbox63:turn_0002

Rating: **major** — The email consists of an explicit person's name, but PERSON is absent.

V2 spans: (none)

> Ashley Landry

### mailex:train:ybarbo-p_inbox101:turn_0000

Rating: **major** — The umbrella TASK is present, but the explicit response request and Friday deadline are omitted.

V2 spans: TASK='need the following four issues resolved'

> Hello, I am a Tax Analyst currently working on Co. 102's (The Protane Corporation) and Co. 214's (Citadel Corporation Limited) federal tax returns. I need the following four issues resolved to complete their tax returns. If you are not the correct accountant (s), could you please tell me who is? I would appreciate this information by Friday, April 27. It appears that on November 3, 2000 Co. 214 sold its 100% interest in Co. 218 (Citadel Venezolana, S.A.) to Co. 102 for 8,000,000 Venezuelan Bolivars. (If you need documentation for your research, I have the interoffice memo concerning this transaction.) There are four issues I have with this transaction: 1) As of 12/31/00, Co. 214 still has an Investment in Subsidiary balance of $1,760,000 and Equity Earnings of $494,508.83 relating to Co. 218. Should not these balances be $0? Also would there have been an intercompany gain/loss associated with this stock sale? 2) As of 12/31/00, Co. 102 shows no Investment in Subsidiary nor Equity Earnings balance relating to Co. 218. Should not there be a balance for Co. 218 which equals the USD equivalent of $8,000,000 Venezuelan Bolivars? Also, should not the Equity Earnings ($494,508.83) from Co. 218 posted on Co. 214 be posted on Co. 102? 3) As of 12/31/00, Co. 218 shows capital stock of $1,760,000 owned by Co. 214. Should not this capital stock be shown to be owned by Co. 102? 4) As of 12/31/00, Co. 214 is showing a $6,000,000 entry in `` Other Deductions '' (The credit side of the journal entry hits `` Deferred Credits. ''). I need more detail concerning this amount. Could this be the consideration received from Co. 102 relating to the stock sale mentioned above? If you have any questions please feel free to contact me.

### mailex:train:ybarbo-p_inbox101:turn_0002

Rating: **acceptable** — Thanks-only reply correctly remains an empty-task negative.

V2 spans: (none)

> Thanks!

