You are a careful human annotator validating an automatic grader for the PopQA benchmark. For each row, decide whether the model's ANSWER line is a correct answer to the question, judged against the dataset gold answer.

Rules:
- Label 1 if the answer names the same entity as the gold answer (any alias, spelling variant, or a clearly equivalent name), even if it adds harmless extra words (e.g. "London, England" for gold "London").
- Label 0 if it names a different entity, is vague/hedged without committing to the gold entity, lists several candidates, or is empty/refuses.
- Judge against the gold answer as given, even if you believe the gold is wrong; but if the answer is at a different granularity that contains/is contained by the gold (city vs. province, etc.), label 0 unless it names the gold entity.
- Do not use outside tools.

Output ONLY lines of the form `<row>,<0|1>` for every row 1..169, nothing else.

row	question	gold_answer	gold_aliases	answer_line
1	In what city was William Osler born?	Ontario	Ontario | ONT | ON	Toronto
2	In what city was William Osler born?	Ontario	Ontario | ONT | ON	London
3	In what city was William Osler born?	Ontario	Ontario | ONT | ON	London, England
4	In what city was William Osler born?	Ontario	Ontario | ONT | ON	Boston
5	In what city was C. N. Annadurai born?	Kanchipuram	Kanchipuram | Kancheepuram	Coimbatore, Tamil Nadu, India
6	In what city was C. N. Annadurai born?	Kanchipuram	Kanchipuram | Kancheepuram	Pudukkottai
7	In what city was C. N. Annadurai born?	Kanchipuram	Kanchipuram | Kancheepuram	Madurai
8	In what city was C. N. Annadurai born?	Kanchipuram	Kanchipuram | Kancheepuram	Tiruchirappalli
9	What is the capital of Missouri?	Jefferson City	Jefferson City | Jefferson City, Missouri	Jefferson City
10	What is the capital of Missouri?	Jefferson City	Jefferson City | Jefferson City, Missouri	Jefferson City
11	What is the capital of Missouri?	Jefferson City	Jefferson City | Jefferson City, Missouri	Jefferson City
12	What is the capital of Missouri?	Jefferson City	Jefferson City | Jefferson City, Missouri	Jefferson City
13	In what country is Home?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	United Kingdom
14	In what country is Home?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	Home is not a country. It is a concept that refers to a place of residence or comfort.
15	In what country is Home?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	United States
16	In what country is Home?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	United Kingdom
17	What is the capital of Province of Canada?	Montreal	Montreal | Montréal | City of Montreal | Montreal, Quebec | Ville de Montréal | Ville de Montreal	Ottawa
18	What is the capital of Province of Canada?	Montreal	Montreal | Montréal | City of Montreal | Montreal, Quebec | Ville de Montréal | Ville de Montreal	Toronto
19	What is the capital of Province of Canada?	Montreal	Montreal | Montréal | City of Montreal | Montreal, Quebec | Ville de Montréal | Ville de Montreal	Ottawa
20	What is the capital of Province of Canada?	Montreal	Montreal | Montréal | City of Montreal | Montreal, Quebec | Ville de Montréal | Ville de Montreal	Montreal
21	What is the capital of Province of Canada?	Montreal	Montreal | Montréal | City of Montreal | Montreal, Quebec | Ville de Montréal | Ville de Montreal	Kingston
22	What is the capital of Uganda?	Kampala	Kampala	Kampala
23	What is the capital of Uganda?	Kampala	Kampala	Kampala
24	What is the capital of Uganda?	Kampala	Kampala	Kampala
25	What is the capital of Uganda?	Kampala	Kampala	Kampala
26	What is the capital of Uganda?	Kampala	Kampala	Kampala
27	In what country is Pine Hills?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	United States
28	In what country is Pine Hills?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	United States
29	In what country is Pine Hills?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	United States
30	In what country is Pine Hills?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	Australia
31	In what country is Pine Hills?	United States of America	United States of America | the United States of America | America | U.S.A. | USA | U.S. | US | the US | the USA | US of A | the United States | U. S. A. | U. S. | the States | the U.S. | 'Merica | U.S | United States | 'Murica	Jamaica
32	Who is the father of Tokugawa Ieyasu?	Matsudaira Hirotada	Matsudaira Hirotada	Matsudaira Masudaiyo
33	Who is the father of Tokugawa Ieyasu?	Matsudaira Hirotada	Matsudaira Hirotada	Nobufusa Asakichi
34	Who is the father of Tokugawa Ieyasu?	Matsudaira Hirotada	Matsudaira Hirotada	Matsudaira Sadanobu (through adoption)
35	Who is the father of Tokugawa Ieyasu?	Matsudaira Hirotada	Matsudaira Hirotada	Tokugawa Tadokoro
36	In what city was Batman born?	Gotham City	Gotham City | Gotham	Gotham City
37	In what city was Batman born?	Gotham City	Gotham City | Gotham	Gotham City
38	In what city was Batman born?	Gotham City	Gotham City | Gotham	Gotham City
39	In what city was Batman born?	Gotham City	Gotham City | Gotham	Batman was born in Detroit, Michigan. This is a fact established by DC Comics as a character originating in the city of Gotham City, but he was raised in the fictional city of Gotham City, Michigan.
40	What is the capital of Piauí?	Teresina	Teresina	Teresina
41	What is the capital of Piauí?	Teresina	Teresina	Teresina
42	What is the capital of Piauí?	Teresina	Teresina	Teresina
43	Who is the father of Legion?	Professor X	Professor X | Charles Xavier | Professor Charles Xavier	Friedrich Nietzsche
44	Who is the father of Legion?	Professor X	Professor X | Charles Xavier | Professor Charles Xavier	High confidence, the father of Legion is Jean Giraud (also known as J.C. Pensées).
45	Who is the father of Legion?	Professor X	Professor X | Charles Xavier | Professor Charles Xavier	The Father (Marvel Comics)
46	Who is the father of Legion?	Professor X	Professor X | Charles Xavier | Professor Charles Xavier	Clint Eastwood
47	Who is the mother of Krishna?	Devaki	Devaki	Devaki
48	Who is the mother of Krishna?	Devaki	Devaki	Devaki
49	Who is the mother of Krishna?	Devaki	Devaki	Devaki
50	Who is the mother of Krishna?	Devaki	Devaki	Devaki
51	Who is the mother of Krishna?	Devaki	Devaki	Devaki
52	What is the capital of City of Newcastle?	Newcastle	Newcastle | Newcastle, New South Wales | Newcastle, New South Wales, Australia	Newcastle, New South Wales, Australia
53	What is the capital of City of Newcastle?	Newcastle	Newcastle | Newcastle, New South Wales | Newcastle, New South Wales, Australia	Newcastle is a city within the state of New South Wales, Australia. The capital of New South Wales is Sydney. Therefore, the capital of Newcastle is not a separate entity but rather the state's capital.
54	What is the capital of City of Newcastle?	Newcastle	Newcastle | Newcastle, New South Wales | Newcastle, New South Wales, Australia	Newcastle upon Tyne
55	What is the capital of City of Newcastle?	Newcastle	Newcastle | Newcastle, New South Wales | Newcastle, New South Wales, Australia	Newcastle upon Tyne
56	Who is the mother of Mary in Islam?	Saint Anne	Saint Anne | Saint Anne | St. Anne | St. Anna | St Anne | St Anna | Anne | Anna | Saint Anna	Not applicable in Islamic belief.
57	Who is the mother of Mary in Islam?	Saint Anne	Saint Anne | Saint Anne | St. Anne | St. Anna | St Anne | St Anna | Anne | Anna | Saint Anna	Fatimah, daughter of Prophet Muhammad and Khadijah.
58	Who is the mother of Mary in Islam?	Saint Anne	Saint Anne | Saint Anne | St. Anne | St. Anna | St Anne | St Anna | Anne | Anna | Saint Anna	Aisha
59	Who is the mother of Mary in Islam?	Saint Anne	Saint Anne | Saint Anne | St. Anne | St. Anna | St Anne | St Anna | Anne | Anna | Saint Anna	Mary
60	Who is the mother of Thomas Jefferson?	Jane Randolph Jefferson	Jane Randolph Jefferson	Martha Jefferson Randolph
61	Who is the mother of Thomas Jefferson?	Jane Randolph Jefferson	Jane Randolph Jefferson	Martha Wayles
62	Who is the mother of Thomas Jefferson?	Jane Randolph Jefferson	Jane Randolph Jefferson	Martha Skelton Jefferson
63	Who is the mother of Thomas Jefferson?	Jane Randolph Jefferson	Jane Randolph Jefferson	Jane Randolph
64	What is the capital of McDowell County?	Welch	Welch | Welch, West Virginia	Huntingdon
65	What is the capital of McDowell County?	Welch	Welch | Welch, West Virginia	Not applicable (as McDowell County is a county and not a country or a state)
66	What is the capital of McDowell County?	Welch	Welch | Welch, West Virginia	Elkins
67	What is the capital of McDowell County?	Welch	Welch | Welch, West Virginia	Hayesville
68	What is the capital of Almoravid dynasty?	Marrakesh	Marrakesh | Marrakech, Morocco | Marrakech | Aghmat	Marrakech
69	What is the capital of Almoravid dynasty?	Marrakesh	Marrakesh | Marrakech, Morocco | Marrakech | Aghmat	Marrakech
70	What is the capital of Almoravid dynasty?	Marrakesh	Marrakesh | Marrakech, Morocco | Marrakech | Aghmat	None, as the Almoravid dynasty did not have a capital city. They were a Berber Islamic Kingdom that used Marrakesh as their capital when they conquered it in 1062. The Almoravid dynasty emerged from the High Atlas mountains in Morocco, and their influence was primarily centered around this region.
71	What is the capital of Almoravid dynasty?	Marrakesh	Marrakesh | Marrakech, Morocco | Marrakech | Aghmat	Undetermined
72	What is the capital of United States of America?	Washington, D.C.	Washington, D.C. | Washington | Washington DC | Washington, DC | DC | D.C. | District of Columbia | Washington, District of Columbia | Washington D.C. | The District	Washington, D.C.
73	What is the capital of United States of America?	Washington, D.C.	Washington, D.C. | Washington | Washington DC | Washington, DC | DC | D.C. | District of Columbia | Washington, District of Columbia | Washington D.C. | The District	Washington, D.C.
74	What is the capital of United States of America?	Washington, D.C.	Washington, D.C. | Washington | Washington DC | Washington, DC | DC | D.C. | District of Columbia | Washington, District of Columbia | Washington D.C. | The District	Washington, D.C.
75	What is the capital of United States of America?	Washington, D.C.	Washington, D.C. | Washington | Washington DC | Washington, DC | DC | D.C. | District of Columbia | Washington, District of Columbia | Washington D.C. | The District	Washington D.C.
76	What is the capital of United States of America?	Washington, D.C.	Washington, D.C. | Washington | Washington DC | Washington, DC | DC | D.C. | District of Columbia | Washington, District of Columbia | Washington D.C. | The District	Washington, D.C.
77	Who is the father of Gillian Baverstock?	Hugh Alexander Pollock	Hugh Alexander Pollock	John Baverstock
78	Who is the father of Gillian Baverstock?	Hugh Alexander Pollock	Hugh Alexander Pollock	None of the sources I could find provide information about who the father of Gillian Baverstock is.
79	Who is the father of Gillian Baverstock?	Hugh Alexander Pollock	Hugh Alexander Pollock	Christopher Gower (if referring to Gillian Baverstock-Gower)
80	Who is the father of Gillian Baverstock?	Hugh Alexander Pollock	Hugh Alexander Pollock	David Baverstock
81	Who is the father of Corbin Bleu?	David Reivers	David Reivers	The father of Corbin Bleu is David Hasselhoff, a well-known actor and singer.
82	Who is the father of Corbin Bleu?	David Reivers	David Reivers	Thomas Bleu
83	Who is the father of Corbin Bleu?	David Reivers	David Reivers	Steve Blue
84	What is the capital of North Carolina?	Raleigh	Raleigh | Raleigh, North Carolina | Raleigh, NC	Raleigh
85	What is the capital of North Carolina?	Raleigh	Raleigh | Raleigh, North Carolina | Raleigh, NC	Raleigh
86	What is the capital of North Carolina?	Raleigh	Raleigh | Raleigh, North Carolina | Raleigh, NC	Raleigh
87	What is the capital of North Carolina?	Raleigh	Raleigh | Raleigh, North Carolina | Raleigh, NC	Raleigh
88	In what city was Franky Zapata born?	Marseille	Marseille | Massaliotes | Massalia | Marsailles | Marseilles | Marsielles | Marsielle | City of Marseille | Marsaille | Marsiglia | Marseille, France | Ville-sans-Nom | Sans-Nom	Paris
89	In what city was Franky Zapata born?	Marseille	Marseille | Massaliotes | Massalia | Marsailles | Marseilles | Marsielles | Marsielle | City of Marseille | Marsaille | Marsiglia | Marseille, France | Ville-sans-Nom | Sans-Nom	Sète
90	In what city was Franky Zapata born?	Marseille	Marseille | Massaliotes | Massalia | Marsailles | Marseilles | Marsielles | Marsielle | City of Marseille | Marsaille | Marsiglia | Marseille, France | Ville-sans-Nom | Sans-Nom	Valencia, Spain
91	In what city was Franky Zapata born?	Marseille	Marseille | Massaliotes | Massalia | Marsailles | Marseilles | Marsielles | Marsielle | City of Marseille | Marsaille | Marsiglia | Marseille, France | Ville-sans-Nom | Sans-Nom	Marseille
92	In what city was Franky Zapata born?	Marseille	Marseille | Massaliotes | Massalia | Marsailles | Marseilles | Marsielles | Marsielle | City of Marseille | Marsaille | Marsiglia | Marseille, France | Ville-sans-Nom | Sans-Nom	Madrid
93	Who is the mother of Paul I of Russia?	Catherine II of Russia	Catherine II of Russia | Ekaterina Alexeyevna | Sophie Friederike Auguste von Anhalt-Zerbst | Empress Catherine II | Екатерина II Великая | Czarina of Russia Catherine II | Empress of Russia Catherine II | Catherine II | Ekaterina II of Russia | Catherine the Great	Anna Ioannovna of Russia
94	Who is the mother of Paul I of Russia?	Catherine II of Russia	Catherine II of Russia | Ekaterina Alexeyevna | Sophie Friederike Auguste von Anhalt-Zerbst | Empress Catherine II | Екатерина II Великая | Czarina of Russia Catherine II | Empress of Russia Catherine II | Catherine II | Ekaterina II of Russia | Catherine the Great	Maria Feodorovna, Duchess of Mecklenburg-Strelitz
95	Who is the mother of Paul I of Russia?	Catherine II of Russia	Catherine II of Russia | Ekaterina Alexeyevna | Sophie Friederike Auguste von Anhalt-Zerbst | Empress Catherine II | Екатерина II Великая | Czarina of Russia Catherine II | Empress of Russia Catherine II | Catherine II | Ekaterina II of Russia | Catherine the Great	Catherine the Great
96	Who is the mother of Paul I of Russia?	Catherine II of Russia	Catherine II of Russia | Ekaterina Alexeyevna | Sophie Friederike Auguste von Anhalt-Zerbst | Empress Catherine II | Екатерина II Великая | Czarina of Russia Catherine II | Empress of Russia Catherine II | Catherine II | Ekaterina II of Russia | Catherine the Great	Catherine the Great
97	What is the capital of Uzbekistan?	Tashkent	Tashkent	Tashkent
98	What is the capital of Uzbekistan?	Tashkent	Tashkent	Tashkent
99	What is the capital of Uzbekistan?	Tashkent	Tashkent	Tashkent
100	What is the capital of Uzbekistan?	Tashkent	Tashkent	Tashkent
101	Who is the father of Salmon?	Nahshon	Nahshon	John Henry Salmon
102	Who is the father of Salmon?	Nahshon	Nahshon	James Salmon
103	Who is the father of Salmon?	Nahshon	Nahshon	Salmon are not a species of animal, but rather a type of fish. There is no individual who can be called the "father of Salmon."
104	Who is the father of Salmon?	Nahshon	Nahshon	Anisakis primigenus
105	Who is the father of Salmon?	Nahshon	Nahshon	Unknown (wild Salmon) or the specific male Salmon in controlled breeding programs.
106	Who is the father of Fahd bin Abdulaziz Al Saud?	Ibn Saud	Ibn Saud | ʻAbd al-ʻAzīz ibn ʻAbd al-Raḥmān ibn Faisal Āl Saʻūd, | Abdulaziz | Abdulaziz ibn Abdul Rahman ibn Faisal ibn Turki ibn Abdullah ibn Muhammad Al Saud | King Abdulaziz bin Abdul Rahman | King Abdulaziz of Saudi Arabia | Abdulaziz bin Abdul Rahman Al Saud	King Faisal of Saudi Arabia
107	Who is the father of Fahd bin Abdulaziz Al Saud?	Ibn Saud	Ibn Saud | ʻAbd al-ʻAzīz ibn ʻAbd al-Raḥmān ibn Faisal Āl Saʻūd, | Abdulaziz | Abdulaziz ibn Abdul Rahman ibn Faisal ibn Turki ibn Abdullah ibn Muhammad Al Saud | King Abdulaziz bin Abdul Rahman | King Abdulaziz of Saudi Arabia | Abdulaziz bin Abdul Rahman Al Saud	Abdulaziz Al Saud
108	Who is the father of Fahd bin Abdulaziz Al Saud?	Ibn Saud	Ibn Saud | ʻAbd al-ʻAzīz ibn ʻAbd al-Raḥmān ibn Faisal Āl Saʻūd, | Abdulaziz | Abdulaziz ibn Abdul Rahman ibn Faisal ibn Turki ibn Abdullah ibn Muhammad Al Saud | King Abdulaziz bin Abdul Rahman | King Abdulaziz of Saudi Arabia | Abdulaziz bin Abdul Rahman Al Saud	Fahd bin Abdulaziz Al Saud
109	What is the capital of Minnesota?	Saint Paul	Saint Paul | St. Paul | Saint Paul, Minnesota | St. Paul, Minnesota | St Paul | St Paul, Minnesota	Saint Paul
110	What is the capital of Minnesota?	Saint Paul	Saint Paul | St. Paul | Saint Paul, Minnesota | St. Paul, Minnesota | St Paul | St Paul, Minnesota	Saint Paul
111	What is the capital of Minnesota?	Saint Paul	Saint Paul | St. Paul | Saint Paul, Minnesota | St. Paul, Minnesota | St Paul | St Paul, Minnesota	Saint Paul
112	What is the capital of Minnesota?	Saint Paul	Saint Paul | St. Paul | Saint Paul, Minnesota | St. Paul, Minnesota | St Paul | St Paul, Minnesota	Saint Paul
113	What is the capital of Minnesota?	Saint Paul	Saint Paul | St. Paul | Saint Paul, Minnesota | St. Paul, Minnesota | St Paul | St Paul, Minnesota	St. Paul
114	What is the capital of Province of Georgia?	Savannah	Savannah | Savannah, Georgia	Tbilisi
115	What is the capital of Province of Georgia?	Savannah	Savannah | Savannah, Georgia	Tbilisi
116	What is the capital of Province of Georgia?	Savannah	Savannah | Savannah, Georgia	Tbilisi
117	What is the capital of Province of Georgia?	Savannah	Savannah | Savannah, Georgia	Tbilisi
118	What is the capital of Province of Georgia?	Savannah	Savannah | Savannah, Georgia	Albany
119	What is the capital of Grand Duchy of Finland?	Helsinki	Helsinki | Helsingfors | Helsingia	Helsinki
120	What is the capital of Grand Duchy of Finland?	Helsinki	Helsinki | Helsingfors | Helsingia	Helsinki
121	What is the capital of Grand Duchy of Finland?	Helsinki	Helsinki | Helsingfors | Helsingia	Helsinki
122	What is the capital of Grand Duchy of Finland?	Helsinki	Helsinki | Helsingfors | Helsingia	The capital of Grand Duchy of Finland is Helsinki. This information is based on historical facts and is widely accepted by geographical and historical sources.
123	What is the capital of Grand Duchy of Finland?	Helsinki	Helsinki | Helsingfors | Helsingia	Helsinki
124	Who is the father of Melora Hardin?	Jerry Hardin	Jerry Hardin	Derek Hardin
125	Who is the father of Melora Hardin?	Jerry Hardin	Jerry Hardin	Edward Marden Hardin
126	Who is the father of Melora Hardin?	Jerry Hardin	Jerry Hardin	Robert Hardin
127	Who is the father of Melora Hardin?	Jerry Hardin	Jerry Hardin	Robert Hardin
128	In what country is Clube Náutico Capibaribe?	Brazil	Brazil | Federative Republic of Brazil | BR | BRA | br | 🇧🇷	Brazil
129	In what country is Clube Náutico Capibaribe?	Brazil	Brazil | Federative Republic of Brazil | BR | BRA | br | 🇧🇷	Brazil
130	In what country is Clube Náutico Capibaribe?	Brazil	Brazil | Federative Republic of Brazil | BR | BRA | br | 🇧🇷	Brazil
131	Who is the mother of Otto von Habsburg?	Zita of Bourbon-Parma	Zita of Bourbon-Parma | Zita of Bourbon Parma | Servant of God Zita of Austria-Hungary	Archduchess Eleonore of Austria
132	Who is the mother of Otto von Habsburg?	Zita of Bourbon-Parma	Zita of Bourbon-Parma | Zita of Bourbon Parma | Servant of God Zita of Austria-Hungary	Anna Maria Josepha Theresa of Austria
133	Who is the mother of Otto von Habsburg?	Zita of Bourbon-Parma	Zita of Bourbon-Parma | Zita of Bourbon Parma | Servant of God Zita of Austria-Hungary	Princess Irmgard von Habsburg
134	What is the capital of Greece?	Athens	Athens	Athens
135	What is the capital of Greece?	Athens	Athens	Athens
136	What is the capital of Greece?	Athens	Athens	Athens
137	What is the capital of Greece?	Athens	Athens	Athens
138	What is the capital of Greece?	Athens	Athens	Athens
139	Who is the father of Dub?	Malcolm I of Scotland	Malcolm I of Scotland	David
140	Who is the father of Dub?	Malcolm I of Scotland	Malcolm I of Scotland	King Jambo
141	Who is the father of Dub?	Malcolm I of Scotland	Malcolm I of Scotland	Without additional context, it's not possible to provide a name.
142	Who is the father of Dub?	Malcolm I of Scotland	Malcolm I of Scotland	N/A (Dub is not a person)
143	Who is the father of Dub?	Malcolm I of Scotland	Malcolm I of Scotland	Joseph Dubieling
144	What is the capital of State of Mexico?	Toluca	Toluca | Toluca de Lerdo	Mexico City
145	What is the capital of State of Mexico?	Toluca	Toluca | Toluca de Lerdo	Mexico City
146	What is the capital of State of Mexico?	Toluca	Toluca | Toluca de Lerdo	Cuernavaca
147	What is the capital of State of Mexico?	Toluca	Toluca | Toluca de Lerdo	Acapulco
148	What is the capital of Pennsylvania?	Harrisburg	Harrisburg | Capital of Pennsylvania | Harrisburg, Pennsylvania	Harrisburg
149	What is the capital of Pennsylvania?	Harrisburg	Harrisburg | Capital of Pennsylvania | Harrisburg, Pennsylvania	Harrisburg
150	What is the capital of Pennsylvania?	Harrisburg	Harrisburg | Capital of Pennsylvania | Harrisburg, Pennsylvania	Harrisburg
151	What is the capital of Pennsylvania?	Harrisburg	Harrisburg | Capital of Pennsylvania | Harrisburg, Pennsylvania	Harrisburg
152	What is the capital of Upper East Region?	Bolgatanga	Bolgatanga	Yenagoa
153	What is the capital of Upper East Region?	Bolgatanga	Bolgatanga	Kumasi
154	What is the capital of Upper East Region?	Bolgatanga	Bolgatanga	Nsawam
155	Who is the father of Joseph?	Jacob	Jacob | Israel | Ya'akov | Ya'aqov | Yaakov | Yisrael	Jacob
156	Who is the father of Joseph?	Jacob	Jacob | Israel | Ya'akov | Ya'aqov | Yaakov | Yisrael	Jacob
157	Who is the father of Joseph?	Jacob	Jacob | Israel | Ya'akov | Ya'aqov | Yaakov | Yisrael	Jacob
158	Who is the father of Joseph?	Jacob	Jacob | Israel | Ya'akov | Ya'aqov | Yaakov | Yisrael	Low confidence, as Joseph is a biblical figure and the lineage from his father to him is not explicitly stated in the Bible. While some sources may speculate on Joseph's father, such claims cannot be verified historically or biblically with certainty.
159	Who is the father of Joseph?	Jacob	Jacob | Israel | Ya'akov | Ya'aqov | Yaakov | Yisrael	Jacob
160	What is the capital of Azerbaijan?	Baku	Baku | City of Winds	Baku
161	What is the capital of Azerbaijan?	Baku	Baku | City of Winds	Baku
162	What is the capital of Azerbaijan?	Baku	Baku | City of Winds	Baku
163	What is the capital of Azerbaijan?	Baku	Baku | City of Winds	Baku
164	What is the capital of Azerbaijan?	Baku	Baku | City of Winds	Baku
165	Who is the father of Monthu?	Amun	Amun | Amún | Amon Ra | Amen | Amon	Unu
166	Who is the father of Monthu?	Amun	Amun | Amún | Amon Ra | Amen | Amon	Montuemhetep
167	Who is the father of Monthu?	Amun	Amun | Amún | Amon Ra | Amen | Amon	Unknown (often associated with Min)
168	Who is the father of Monthu?	Amun	Amun | Amún | Amon Ra | Amen | Amon	Theon
169	Who is the father of Monthu?	Amun	Amun | Amún | Amon Ra | Amen | Amon	Ahmose-Sin, Pharaoh of the Eighteenth Dynasty of Egypt